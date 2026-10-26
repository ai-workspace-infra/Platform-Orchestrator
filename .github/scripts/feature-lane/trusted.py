#!/usr/bin/env python3
"""Authenticated, read-only GitHub evidence adapter. No caller evidence JSON."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
REPOSITORY = 'ai-workspace-infra/platform-ops-toolkit'
POLICY_PATH = '.github/policies/feature-lane.json'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reader = load('feature_shared_artifact_reader', ROOT / '.github/scripts/acceptance/migration_matrix.py')
gate = load('feature_contract', Path(__file__).with_name('gate.py'))


def policy_at(commit):
    gate.require(gate.sha(commit), 'reviewed full policy SHA required')
    current = reader.api(f'repos/{REPOSITORY}/git/ref/heads/main')
    current_sha = current.get('object', {}).get('sha')
    gate.require(gate.sha(current_sha), 'trusted main identity unavailable')
    compared = reader.api(f'repos/{REPOSITORY}/compare/{commit}...{current_sha}')
    gate.require(compared.get('status') in ('ahead', 'identical'), 'policy must be reachable from trusted main')
    def content_at(ref):
        try:
            content = reader.api(f'repos/{REPOSITORY}/contents/{POLICY_PATH}?ref={ref}')
        except Exception:
            raise gate.Blocked('Trusted feature policy file unavailable at pinned/current main') from None
        gate.require(content.get('type') == 'file' and content.get('path') == POLICY_PATH and
                     type(content.get('size')) is int and content['size'] <= 100_000 and gate.sha(content.get('sha')),
                     'missing or oversized trusted policy')
        return content
    content = content_at(commit)
    active = content_at(current_sha)
    gate.require(content['sha'] == active['sha'], 'pinned policy differs from current trusted main policy')
    return json.loads(base64.b64decode(content['content'], validate=False))


def pull(source, stage):
    repo, number = source['repository'], source['pr']
    p = reader.api(f'repos/{repo}/pulls/{number}')
    snapshot = {'repository': p.get('base', {}).get('repo', {}).get('full_name'), 'number': p.get('number'),
                'head_sha': p.get('head', {}).get('sha'), 'head_repository': p.get('head', {}).get('repo', {}).get('full_name'),
                'base_ref': p.get('base', {}).get('ref'), 'state': str(p.get('state')).upper(),
                'merged': p.get('merged'), 'merge_sha': p.get('merge_commit_sha')}
    if stage != 'uat':
        gate.verify_pr(source, snapshot, 'sit')
    return snapshot


def artifact(locator):
    repo = locator['repository']
    gate.require(isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'invalid evidence repository')
    raw = reader.api(f'repos/{repo}/actions/runs/{locator["run_id"]}')
    run = {'repository': raw.get('repository', {}).get('full_name'), 'path': raw.get('path', '').split('@')[0],
           'head_sha': raw.get('head_sha'), 'event': raw.get('event'), 'id': raw.get('id'),
           'attempt': raw.get('run_attempt'), 'status': raw.get('status'), 'conclusion': raw.get('conclusion')}
    gate.verify_run(run, locator, locator['sha'], locator['event'])
    gate.require(run['id'] == locator['run_id'] and run['attempt'] == locator['attempt'] and
                 raw.get('head_repository', {}).get('full_name') == repo, 'wrong run/attempt or fork producer')
    name = locator['artifact_name']
    gate.require(name.endswith(f'-{run["id"]}-{run["attempt"]}'), 'artifact name must bind run and attempt')
    payload = reader.artifact_file(repo, locator['artifact_id'], run['id'], run['attempt'], name,
                                   locator['filename'], locator['sha'])
    run.update(artifact_id=locator['artifact_id'], document_sha256=hashlib.sha256(payload).hexdigest())
    return json.loads(payload), run


def authorization(policy, fingerprint, stage):
    auth = policy.get('authorization')
    gate.require(isinstance(auth, dict) and auth.get('kind') == 'issue_comment',
                 'no supported reviewed human authorization source configured')
    repo, issue, comment_id = auth['repository'], auth['issue'], auth['comment_id']
    gate.require(isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) and
                 type(issue) is int and issue > 0 and type(comment_id) is int and comment_id > 0, 'invalid authorization locator')
    gate.require(f'https://github.com/{repo}/issues/{issue}' == policy['task_url'], 'authorization issue differs from task')
    record = reader.api(f'repos/{repo}/issues/{issue}')
    gate.require(record.get('number') == issue and 'pull_request' not in record and
                 record.get('url') == f'https://api.github.com/repos/{repo}/issues/{issue}', 'wrong authorization issue')
    comments = []
    for page in range(1, 21):
        rows = reader.api(f'repos/{repo}/issues/{issue}/comments?per_page=100&page={page}')
        comments.extend(rows)
        if len(rows) < 100:
            break
    else:
        raise gate.Blocked('authorization history exceeds bounded lookup')
    selected = [c for c in comments if c.get('id') == comment_id]
    gate.require(len(selected) == 1, 'authorization comment missing or deleted')
    c = selected[0]
    actor = c.get('user', {}).get('login')
    body = f'APPROVE feature-candidate {fingerprint} action={stage}'
    gate.require(actor in policy['approvers'] and c.get('user', {}).get('type') == 'User' and
                 c.get('author_association') in ('OWNER', 'MEMBER', 'COLLABORATOR') and
                 c.get('issue_url') == record['url'] and
                 c.get('html_url') == f'https://github.com/{repo}/issues/{issue}#issuecomment-{comment_id}' and
                 c.get('body', '').strip() == body and
                 c.get('created_at') and c.get('created_at') == c.get('updated_at'),
                 'authorization author/action/candidate differs or comment edited')
    for later in comments:
        if later.get('user', {}).get('login') == actor and (later.get('id', 0) > comment_id or
                later.get('updated_at', '') > c['created_at']):
            words = later.get('body', '').strip().split()
            if words and words[0] in ('REVOKE', 'REJECT') and fingerprint in words:
                raise gate.Blocked('human authorization revoked or rejected')
    return {'actor': actor, 'decision': 'approved', 'candidate_sha256': fingerprint,
            'evidence_url': c.get('html_url', '')}


def verified(candidate, stage, policy_commit):
    """Only raw selectors and candidate declaration enter; provenance is fetched."""
    try:
        policy = policy_at(policy_commit)
        gate.require(stage in ('sit', 'merge', 'uat'), 'unsupported stage')
        gate.require(candidate.get('task_url') == policy['task_url'], 'wrong feature task')
        fingerprint = gate.validate_candidate(candidate, policy)
        prs = {}
        for source in candidate['sources']:
            if source['kind'] == 'feature':
                prs[source['repository']] = pull(source, stage)
            proof, _ = artifact(policy['builds'][source['repository']])
            gate.require(proof.get('repository') == source['repository'] and proof.get('source_sha') == source['sha'] and
                         proof.get('image') == source['image'], 'build manifest source/image mismatch')
        receipt = run = auth = None
        if stage in ('merge', 'uat'):
            receipt, run = artifact(policy['acceptance_owner'])
            auth = authorization(policy, fingerprint, stage)
        if stage == 'uat':
            for source in candidate['sources']:
                if source['kind'] != 'feature':
                    continue
                locator = policy['merge_builds'][source['repository']]
                p = prs[source['repository']]
                gate.require(locator['repository'] == source['repository'] and locator['sha'] == p['merge_sha'],
                             'merge manifest producer differs from merged source')
                proof, producer = artifact(locator)
                gate.require(proof.get('repository') == source['repository'], 'foreign merged artifact manifest')
                source_tree = reader.api(f'repos/{source["repository"]}/git/commits/{source["sha"]}')
                merged_tree = reader.api(f'repos/{source["repository"]}/git/commits/{p["merge_sha"]}')
                p['merge_artifact'] = dict(proof, manifest_sha256=producer['document_sha256'], source_tree_sha=source_tree['tree']['sha'],
                                           merge_tree_sha=merged_tree['tree']['sha'])
        result = gate._evaluate(candidate, policy, stage, prs, receipt, run, auth)
        result.update(status='VERIFIED_GATE', evidence_kind='github_retrieved', policy_sha=policy_commit)
        return result
    except gate.Blocked:
        raise
    except Exception as exc:
        # Never publish API bodies, transport errors or downloaded evidence.
        raise gate.Blocked('Trusted policy or GitHub evidence unavailable or invalid') from None
