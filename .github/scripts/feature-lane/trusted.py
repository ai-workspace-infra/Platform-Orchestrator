#!/usr/bin/env python3
"""Authenticated, read-only GitHub evidence adapter. No caller evidence JSON."""
import base64
import hashlib
import importlib.util
import json
import os
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
chart = load('feature_chart_provenance', Path(__file__).with_name('chart.py'))

_authenticated_api = reader.api


def feature_api(path, binary=False):
    """Select a short-lived installation token by API repository owner.

    Callers supply credentials; this adapter never obtains them or grants
    execution. Without an owner-specific token the existing gh identity applies.
    """
    match = re.match(r'^repos/([^/]+)/[^/]+(?:/|$)', path) if isinstance(path, str) else None
    owner = match.group(1).lower() if match else ''
    key = {'ai-workspace-infra': 'FEATURE_GH_TOKEN_INFRA',
           'ai-workspace-services': 'FEATURE_GH_TOKEN_SERVICES'}.get(owner)
    token = os.environ.get(key) if key else None
    return _authenticated_api(path, binary=binary, token=token or None)


# artifact_file resolves its metadata, run and archive through this same adapter.
reader.api = feature_api


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


def file_at(repo, commit, path):
    gate.require(gate.sha(commit) and isinstance(path, str) and not path.startswith('/') and
                 '..' not in path.split('/') and '\\' not in path, 'unsafe fixed content source')
    from urllib.parse import quote
    record = reader.api(f'repos/{repo}/contents/{quote(path, safe="/")}?ref={commit}')
    gate.require(record.get('type') == 'file' and record.get('path') == path and record.get('encoding') == 'base64' and
                 type(record.get('size')) is int and record['size'] <= 1_000_000, 'missing or oversized fixed content')
    raw = base64.b64decode(record['content'])
    gate.require(len(raw) <= 1_000_000, 'oversized fixed content bytes')
    return hashlib.sha256(raw).hexdigest()


def verified_content_identity(repo, commit, policy):
    canonical = policy.get('website_content_canonical_repository')
    valid_repo = r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+'
    gate.require(isinstance(repo, str) and re.fullmatch(valid_repo, repo) and
                 isinstance(canonical, str) and re.fullmatch(valid_repo, canonical) and
                 repo in policy.get('website_content_repositories', []) and gate.sha(commit),
                 'reviewed content repository and commit required')
    original = reader.api(f'repos/{repo}')
    resolved = reader.api(f'repos/{canonical}')
    gate.require(type(original.get('id')) is int and original['id'] > 0 and
                 original.get('id') == resolved.get('id') and
                 resolved.get('full_name', '').lower() == canonical.lower(),
                 'content repository aliases do not resolve to the reviewed identity')
    record = reader.api(f'repos/{canonical}/commits/{commit}')
    gate.require(record.get('sha') == commit, 'verified content commit unavailable')
    return {'repository': canonical, 'sha': commit, 'repository_id': original['id']}


def task_at(candidate, policy):
    url = candidate.get('task_url', '')
    match = re.fullmatch(r'https://github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)', url)
    if match:
        gate.require(match[1] in policy['task_repositories'], 'task repository not approved')
        repo, number = match[1], int(match[2])
        record = reader.api(f'repos/{repo}/issues/{number}')
        gate.require(record.get('number') == number and 'pull_request' not in record and
                     record.get('url') == f'https://api.github.com/repos/{repo}/issues/{number}', 'wrong feature task')
        return {'kind': 'issue', 'repository': repo, 'issue': number}
    match = re.fullmatch(r'https://github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/blob/([0-9a-f]{40})/(.+)', url)
    gate.require(match is not None and any(match[3].startswith(prefix) for prefix in policy.get('task_paths', {}).get(match[1], [])),
                 'immutable task file outside approved roots')
    digest = file_at(match[1], match[2], match[3])
    gate.require(digest == candidate.get('task_sha256'), 'immutable task content hash differs')
    return {'kind': 'file', 'repository': match[1], 'commit': match[2], 'path': match[3], 'sha256': digest}


def verify_main_rehearsal_sources(candidate, policy):
    """Verify the selected baseline is the current Main of each allowed source.

    This is one prerequisite only; it does not authenticate a tag or authorize
    deployment, and must be rechecked before accepting a candidate for use.
    """
    gate.require(candidate.get('candidate_mode') == 'main-rehearsal', 'main rehearsal required')
    gate.require(candidate.get('task_url') in policy.get('main_rehearsal_tasks', []), 'rehearsal task not allowed')
    sources = candidate.get('sources')
    gate.require(isinstance(sources, list) and bool(sources), 'missing rehearsal sources')
    seen = set()
    for source in sources:
        gate.require(isinstance(source, dict), 'invalid rehearsal source')
        repo = source.get('repository')
        gate.require(repo in policy.get('repositories', []) and repo not in seen and
                     source.get('kind') == 'baseline' and source.get('pr') is None and gate.sha(source.get('sha')),
                     'invalid rehearsal baseline')
        seen.add(repo)
        current = reader.api(f'repos/{repo}/git/ref/heads/main')
        gate.require(current.get('object', {}).get('type') == 'commit' and
                     current.get('object', {}).get('sha') == source['sha'], 'rehearsal Main moved or unavailable')


def verify_gitops_domain(candidate, policy, stage):
    """Bind a tagged candidate to reviewed GitOps declaration bytes and ref."""
    selected = candidate.get('gitops')
    repo = policy.get('gitops_repository')
    path = policy.get('gitops_domain_contract_path')
    gate.require(isinstance(selected, dict) and set(selected) == {'repository', 'sha', 'domain_sha256'} and
                 isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) and
                 path == 'docs/features/tagged-sit-domain-contract.yaml' and
                 selected['repository'] == repo and gate.sha(selected['sha']) and gate.sha(selected['domain_sha256'], 64),
                 'missing reviewed GitOps domain binding')
    gate.require(file_at(repo, selected['sha'], path) == selected['domain_sha256'],
                 'GitOps domain declaration differs from candidate')
    configurations = [row for row in candidate.get('configurations', []) if row.get('repository') == repo]
    if configurations:
        gate.require(any(row.get('sha') == selected['sha'] and
                         row.get('paths', {}).get(path) == selected['domain_sha256'] for row in configurations),
                     'GitOps candidate declaration is not bound to selected configuration PR')
    else:
        main = reader.api(f'repos/{repo}/git/ref/heads/main').get('object', {})
        gate.require(main.get('type') == 'commit' and gate.sha(main.get('sha')), 'GitOps Main unavailable')
        if stage in ('sit', 'merge'):
            gate.require(main['sha'] == selected['sha'], 'GitOps Main moved; require new candidate')
        else:
            comparison = reader.api(f'repos/{repo}/compare/{selected["sha"]}...{main["sha"]}')
            gate.require(comparison.get('status') in ('ahead', 'identical'), 'GitOps snapshot not reachable from Main')


def verify_feature_tag(candidate, policy):
    """Check a reviewed tag binding against GitHub; never authorize execution."""
    tag = candidate.get('feature_tag')
    gate.validate_feature_tag(tag, candidate.get('feature_id'))
    bindings = policy.get('feature_tags', {})
    gate.require(isinstance(bindings, dict) and isinstance(bindings.get(tag), dict), 'tag not in reviewed policy')
    binding = bindings[tag]
    repo, object_sha, target_sha = binding.get('repository'), binding.get('tag_object_sha'), binding.get('target_sha')
    gate.require(repo in policy.get('tag_repositories', []) and gate.sha(object_sha) and gate.sha(target_sha) and
                 binding.get('candidate_sha256') == gate.identity(candidate) and
                 binding.get('task_url') == candidate.get('task_url'), 'invalid reviewed tag binding')
    ref = reader.api(f'repos/{repo}/git/ref/tags/{tag}')
    gate.require(ref.get('ref') == 'refs/tags/' + tag and ref.get('object', {}).get('type') == 'tag' and
                 ref.get('object', {}).get('sha') == object_sha, 'tag ref moved or is not annotated')
    obj = reader.api(f'repos/{repo}/git/tags/{object_sha}')
    gate.require(obj.get('sha') == object_sha and obj.get('tag') == tag and
                 obj.get('object', {}).get('type') == 'commit' and obj.get('object', {}).get('sha') == target_sha,
                 'tag object target differs from reviewed binding')
    main = reader.api(f'repos/{repo}/git/ref/heads/main').get('object', {}).get('sha')
    gate.require(gate.sha(main), 'tag repository Main unavailable')
    comparison = reader.api(f'repos/{repo}/compare/{target_sha}...{main}')
    gate.require(comparison.get('status') in ('ahead', 'identical'), 'tag target is not reachable from Main')
    return {'tag': tag, 'repository': repo, 'tag_object_sha': object_sha, 'target_sha': target_sha}


def locator(owner, selectors, source_sha):
    stable = {'repository', 'workflow', 'event', 'filename', 'artifact_prefix'}
    gate.require(isinstance(owner, dict) and stable <= set(owner) and set(owner) <= stable | {'sha'},
                 'owner policy must contain only stable workflow identity')
    gate.require(isinstance(selectors, dict) and set(selectors) == {'run_id', 'attempt', 'artifact_id'} and
                 all(type(v) is int and v > 0 for v in selectors.values()), 'only positive run/artifact/attempt selectors allowed')
    gate.require(gate.sha(source_sha), 'fixed producer source required')
    return dict(owner, **selectors, sha=source_sha,
                artifact_name=f'{owner["artifact_prefix"]}-{selectors["run_id"]}-{selectors["attempt"]}')


def pull(source, stage, task_url, configuration=False, require_task_link=True):
    repo, number = source['repository'], source['pr']
    p = reader.api(f'repos/{repo}/pulls/{number}')
    body = p.get('body') or ''
    linked = re.search(re.escape(task_url)+r'(?![0-9])', body) is not None
    if '/issues/' in task_url:
        task_repo, task_number = task_url.split('github.com/',1)[1].split('/issues/')
        linked = linked or (task_repo == repo and re.search(r'(?<![A-Za-z0-9])#'+task_number+r'(?![0-9])',body) is not None)
    gate.require(linked or not require_task_link, 'source PR is not linked to the selected feature task')
    snapshot = {'repository': p.get('base', {}).get('repo', {}).get('full_name'), 'number': p.get('number'),
                'head_sha': p.get('head', {}).get('sha'), 'head_repository': p.get('head', {}).get('repo', {}).get('full_name'),
                'base_ref': p.get('base', {}).get('ref'), 'base_sha': p.get('base', {}).get('sha'), 'state': str(p.get('state')).upper(),
                'merged': p.get('merged'), 'merge_sha': p.get('merge_commit_sha')}
    if stage != 'uat' and not configuration:
        gate.verify_pr(source, snapshot, 'sit')
    return snapshot


def verify_configuration_diff(row):
    """Every changed path must be among the candidate's fixed declarations."""
    files = reader.api(f'repos/{row["repository"]}/pulls/{row["pr"]}/files?per_page=100&page=1')
    gate.require(isinstance(files, list) and 0 < len(files) <= 64,
                 'configuration PR must contain a bounded set of changes')
    seen = set()
    for item in files:
        path = item.get('filename') if isinstance(item, dict) else None
        gate.require(isinstance(path, str) and path in row['paths'] and path not in seen and
                     item.get('status') in ('added', 'modified'),
                     'configuration PR contains undeclared, renamed or deleted files')
        seen.add(path)


def artifact(locator):
    repo = locator['repository']
    gate.require(isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'invalid evidence repository')
    raw = reader.api(f'repos/{repo}/actions/runs/{locator["run_id"]}')
    run = {'repository': raw.get('repository', {}).get('full_name'), 'path': raw.get('path', '').split('@')[0],
           'head_sha': raw.get('head_sha'), 'event': raw.get('event'), 'id': raw.get('id'),
           'attempt': raw.get('run_attempt'), 'status': raw.get('status'), 'conclusion': raw.get('conclusion'),
           'head_branch': raw.get('head_branch')}
    gate.verify_run(run, locator, locator['sha'], locator['event'])
    gate.require(run['id'] == locator['run_id'] and run['attempt'] == locator['attempt'] and
                 raw.get('head_repository', {}).get('full_name') == repo, 'wrong run/attempt or fork producer')
    name = locator['artifact_name']
    gate.require(name.endswith(f'-{run["id"]}-{run["attempt"]}'), 'artifact name must bind run and attempt')
    payload = reader.artifact_file(repo, locator['artifact_id'], run['id'], run['attempt'], name,
                                   locator['filename'], locator['sha'])
    run.update(artifact_id=locator['artifact_id'], document_sha256=hashlib.sha256(payload).hexdigest())
    return json.loads(payload), run


def verify_build_manifest(proof, run, source):
    """Validate the reviewed owner's manifest against its authenticated run."""
    gate.require(isinstance(proof, dict), 'invalid build manifest')
    if proof.get('schema') == 'main-image-build/v1':
        gate.require(source.get('kind') == 'baseline' and run.get('event') == 'push' and run.get('head_branch') == 'main' and
                     proof.get('event') == 'push' and proof.get('ref') == 'refs/heads/main' and
                     type(proof.get('run_id')) is int and proof['run_id'] == run.get('id') and
                     type(proof.get('attempt')) is int and proof['attempt'] == run.get('attempt') and
                     proof.get('source_repository') == source['repository'] and
                     ('repository' not in proof or proof['repository'] == source['repository']),
                     'main build manifest run or repository mismatch')
    else:
        gate.require(proof.get('repository') == source['repository'], 'build manifest repository mismatch')
    gate.require(proof.get('source_sha') == source['sha'] and proof.get('image') == source['image'],
                 'build manifest source/image mismatch')


def authorization(policy, fingerprint, stage, task, selectors):
    auth = policy.get('authorization')
    gate.require(isinstance(auth, dict) and auth.get('kind') == 'issue_comment',
                 'no supported reviewed human authorization source configured')
    gate.require(isinstance(selectors, dict) and set(selectors) == {'issue', 'comment_id'} and
                 all(type(v) is int and v > 0 for v in selectors.values()), 'only positive issue/comment selectors allowed')
    repo = auth['repository']
    gate.require(isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'invalid authorization repository')
    issue, comment_id = selectors['issue'], selectors['comment_id']
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


def verified(candidate, stage, policy_commit, evidence_selectors=None):
    """Only raw selectors and candidate declaration enter; provenance is fetched."""
    try:
        policy = policy_at(policy_commit)
        gate.require(stage in ('sit', 'merge', 'uat'), 'unsupported stage')
        task = task_at(candidate, policy)
        required = {'builds'} | ({'chart'} if candidate.get('schema') == 2 else set()) | ({'acceptance', 'authorization'} if stage in ('merge', 'uat') else set()) | ({'merge_builds'} if stage == 'uat' else set())
        gate.require(isinstance(evidence_selectors, dict) and set(evidence_selectors) == required, 'wrong evidence selector set')
        sources = {source['repository'] for source in candidate.get('sources', [])}
        gate.require(isinstance(evidence_selectors['builds'], dict) and set(evidence_selectors['builds']) == sources, 'build selector source set differs')
        fingerprint = gate.validate_candidate(candidate, policy)
        if candidate.get('schema') == 2:
            gate.require(task.get('kind') == 'issue', 'feature tag requires a tracked Issue')
            verify_feature_tag(candidate, policy)
            verify_gitops_domain(candidate, policy, stage)
            chart.verify(candidate, policy, evidence_selectors['chart'], reader, file_at)
            frontend_repo = policy.get('feature_sit_frontend_repository')
            gate.require(frontend_repo in sources and frontend_repo in policy.get('repositories', []),
                         'missing reviewed Feature SIT frontend source')
            if candidate.get('candidate_mode') == 'main-rehearsal' and stage == 'sit':
                verify_main_rehearsal_sources(candidate, policy)
        prs = {}
        config_prs = {}
        verified_website_content = None
        verified_builds = {}
        for row in candidate.get('configurations', []):
            key = row['repository']+'#'+str(row['pr'])
            primary = len(candidate['configurations']) == 1 or candidate.get('configuration_entrypoint') == key
            snapshot = pull(row, stage, candidate['task_url'], configuration=True, require_task_link=primary)
            verify_configuration_diff(row)
            snapshot['path_hashes'] = {path: file_at(row['repository'], row['sha'], path) for path in row['paths']}
            if stage == 'uat':
                snapshot['merged_path_hashes'] = {path: file_at(row['repository'], snapshot['merge_sha'], path) for path in row['paths']}
            current = pull(row, stage, candidate['task_url'], configuration=True, require_task_link=primary)
            gate.require(all(current.get(key) == snapshot.get(key) for key in
                             ('repository', 'number', 'head_sha', 'head_repository', 'base_ref', 'base_sha',
                              'state', 'merged', 'merge_sha')), 'configuration PR moved during evidence retrieval')
            config_prs[row['repository']+'#'+str(row['pr'])] = snapshot
        for source in candidate['sources']:
            if source['kind'] == 'feature':
                prs[source['repository']] = pull(source, stage, candidate['task_url'])
            owner = policy['build_owners'][source['repository']]
            gate.require(owner['repository'] == source['repository'], 'foreign source build owner')
            proof, producer = artifact(locator(owner, evidence_selectors['builds'][source['repository']], source['sha']))
            verify_build_manifest(proof, producer, source)
            verified_builds[source['repository']] = {'source_repository': source['repository'],
                                                       'source_sha': source['sha'],
                                                       'image': source['image'],
                                                       'build_run_id': str(producer['id'])}
            if candidate.get('schema') == 2 and source['repository'] == frontend_repo:
                content_repo = source.get('website_content_repository')
                content_sha = source.get('website_content_sha')
                gate.require(content_repo in policy.get('website_content_repositories', []) and gate.sha(content_sha) and
                             proof.get('website_content_repository') == content_repo and
                             proof.get('website_content_sha') == content_sha and
                             proof.get('environment') == 'sit' and proof.get('build_mode') == 'feature-sit' and
                             proof.get('candidate_hostname') == candidate['domains']['sit'],
                             'frontend SIT build inputs differ from candidate')
                verified_website_content = verified_content_identity(content_repo, content_sha, policy)
        if candidate.get('schema') == 2 and candidate.get('candidate_mode') == 'main-rehearsal' and stage == 'sit':
            verify_main_rehearsal_sources(candidate, policy)
            verify_feature_tag(candidate, policy)
        if candidate.get('schema') == 2 and stage == 'sit':
            verify_gitops_domain(candidate, policy, stage)
        receipt = run = auth = None
        if stage in ('merge', 'uat'):
            receipt, run = artifact(locator(policy['acceptance_owner'], evidence_selectors['acceptance'], policy['acceptance_owner']['sha']))
            auth = authorization(policy, fingerprint, stage, task, evidence_selectors['authorization'])
        if stage == 'uat':
            feature_repos = {source['repository'] for source in candidate['sources'] if source['kind'] == 'feature'}
            gate.require(isinstance(evidence_selectors['merge_builds'], dict) and set(evidence_selectors['merge_builds']) == feature_repos, 'merge selector source set differs')
            for source in candidate['sources']:
                if source['kind'] != 'feature':
                    continue
                owner = policy['merge_build_owners'][source['repository']]
                p = prs[source['repository']]
                gate.require(owner['repository'] == source['repository'], 'foreign merge build owner')
                proof, producer = artifact(locator(owner, evidence_selectors['merge_builds'][source['repository']], p['merge_sha']))
                gate.require(proof.get('repository') == source['repository'], 'foreign merged artifact manifest')
                source_tree = reader.api(f'repos/{source["repository"]}/git/commits/{source["sha"]}')
                merged_tree = reader.api(f'repos/{source["repository"]}/git/commits/{p["merge_sha"]}')
                p['merge_artifact'] = dict(proof, manifest_sha256=producer['document_sha256'], source_tree_sha=source_tree['tree']['sha'],
                                           merge_tree_sha=merged_tree['tree']['sha'])
        prefix = auth['evidence_url'].split('#', 1)[0]+'#' if auth else ''
        evaluation_policy = dict(policy, authorization_url_prefix=prefix)
        result = gate._evaluate(candidate, evaluation_policy, stage, prs, receipt, run, auth, config_prs)
        result.update(status='VERIFIED_GATE', evidence_kind='github_retrieved', policy_sha=policy_commit)
        if verified_website_content is not None:
            result['verified_website_content'] = verified_website_content
        if candidate.get('schema') == 2:
            result['verified_chart_digest'] = candidate['chart_digest']
        if candidate.get('components'):
            result['verified_runtime_components'] = {
                name: verified_builds[item['source_repository']]
                for name, item in candidate['components'].items()
            }
        if candidate.get('schema') == 2 and stage == 'sit':
            content = result['verified_website_content']
            result['verified_projection'] = {
                'tagged_lane': {'feature_id': candidate['feature_id'], 'feature_tag': candidate['feature_tag'],
                                'candidate_sha256': result['candidate_sha256']},
                'chart_digest': result['verified_chart_digest'],
                'knowledge': {'repository': content['repository'], 'sha': content['sha']},
                'components': result['verified_runtime_components'],
            }
        return result
    except gate.Blocked:
        raise
    except Exception as exc:
        # Never publish API bodies, transport errors or downloaded evidence.
        raise gate.Blocked('Trusted policy or GitHub evidence unavailable or invalid') from None
