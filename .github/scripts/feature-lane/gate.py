#!/usr/bin/env python3
"""Pure feature-lane control-plane contract; never dispatches or grants approval.

Caller must resolve GitHub PR/run/review snapshots through its trusted adapter.
Fixture snapshots are for offline tests only. A successful decision is a gate
result, not deployment, business acceptance, or an instruction to merge.
"""
import hashlib
import json
import re


class Blocked(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Blocked(message)


def sha(value, length=40):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{%d}' % length, value) is not None


def identity(candidate):
    return hashlib.sha256(json.dumps(candidate, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_candidate(c, policy):
    require(c.get('schema') == 1, 'unsupported candidate schema')
    feature = c.get('feature_id', '')
    require(re.fullmatch(r'[a-z][a-z0-9-]{1,45}', feature) is not None, 'invalid feature id')
    require(re.fullmatch(r'https://github.com/[^/]+/[^/]+/issues/[1-9][0-9]*', c.get('task_url', '')),
            'feature requires a tracked task')
    require(c.get('target') == policy['target'], 'unapproved Dev target')
    require(c.get('environment') == 'dev', 'only a shared Dev host is eligible')
    require(c.get('namespaces') == {'sit': 'feature-' + feature + '-sit', 'uat': 'feature-' + feature + '-uat'},
            'SIT/UAT require distinct feature namespaces')
    domains = c.get('domains', {})
    for stage in ('sit', 'uat'):
        require(domains.get(stage) == feature + '-' + stage + '.' + policy['domain_suffix'],
                'unapproved temporary feature domain')
    for field in ('chart_digest', 'config_sha256', 'data_baseline_sha256'):
        value = c.get(field, '')
        require(sha(value.removeprefix('sha256:') if field == 'chart_digest' else value, 64),
                'missing immutable ' + field)
    sources = c.get('sources', [])
    require(bool(sources), 'missing participating sources')
    seen = set()
    features = 0
    for source in sources:
        repo = source.get('repository')
        require(repo in policy['repositories'] and repo not in seen, 'foreign or duplicate repository')
        seen.add(repo)
        require(sha(source.get('sha')), 'source must be full SHA')
        require(re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', source.get('image', '')), 'image must use digest')
        if source.get('kind') == 'feature':
            require(type(source.get('pr')) is int and source['pr'] > 0, 'feature source requires real PR')
            features += 1
        else:
            require(source.get('kind') == 'baseline' and source.get('pr') is None,
                    'baseline dependencies cannot masquerade as open feature PRs')
    require(features > 0, 'already merged baseline alone cannot establish premerge SIT')
    require(set(c.get('required_tests', [])) == set(policy['required_tests']), 'required acceptance contract mismatch')
    return identity(c)


def verify_pr(source, snapshot, stage):
    require(snapshot.get('repository') == source['repository'] and snapshot.get('number') == source['pr'],
            'wrong PR snapshot')
    require(snapshot.get('head_sha') == source['sha'] and snapshot.get('base_ref') == 'main', 'PR source moved')
    require(snapshot.get('head_repository') == source['repository'], 'fork PR is not a trusted deployment source')
    if stage == 'sit':
        require(snapshot.get('state') == 'OPEN' and snapshot.get('merged') is False, 'SIT needs a real unmerged PR')
    else:
        require(snapshot.get('merged') is True and sha(snapshot.get('merge_sha')), 'UAT needs merged main evidence')


def verify_run(run, expected, source_sha, event):
    require(run.get('repository') == expected['repository'] and run.get('path') == expected['workflow'],
            'foreign evidence owner')
    require(run.get('head_sha') == source_sha and run.get('event') == event, 'evidence source/event mismatch')
    require(type(run.get('id')) is int and run['id'] > 0 and run.get('attempt') == 1,
            'missing or ambiguous evidence run')
    require(run.get('status') == 'completed' and run.get('conclusion') == 'success', 'evidence run not successful')


def _evaluate(c, policy, stage, prs, receipt=None, run=None, authorization=None):
    fingerprint = validate_candidate(c, policy)
    require(stage in ('sit', 'merge', 'uat'), 'unsupported stage')
    for source in c['sources']:
        if source['kind'] == 'feature':
            require(source['repository'] in prs, 'missing live PR snapshot')
            verify_pr(source, prs[source['repository']], 'sit' if stage in ('sit', 'merge') else 'uat')
    if stage in ('merge', 'uat'):
        require(receipt is not None and run is not None, 'missing structured SIT evidence')
        verify_run(run, policy['acceptance_owner'], policy['acceptance_owner']['sha'], 'workflow_dispatch')
        require(receipt.get('schema') == 1 and receipt.get('evidence_kind') == 'live', 'synthetic evidence cannot pass')
        require(receipt.get('run_id') == run['id'] and receipt.get('run_attempt') == run['attempt'], 'receipt/run mismatch')
        require(receipt.get('candidate_sha256') == fingerprint and receipt.get('stage') == 'sit', 'stale SIT candidate')
        require(receipt.get('target') == c['target'] and receipt.get('namespace') == c['namespaces']['sit'],
                'wrong SIT target')
        require(receipt.get('domain') == c['domains']['sit'], 'wrong SIT domain')
        require(receipt.get('image_ids') == {s['repository']: s['image'] for s in c['sources']}, 'runtime image mismatch')
        results = receipt.get('tests', {})
        require(set(results) == set(policy['required_tests']) and all(v == 'PASS' for v in results.values()),
                'missing, blocked or failed acceptance')
        require(receipt.get('data_baseline_sha256') == c['data_baseline_sha256'], 'data baseline moved')
        require(receipt.get('flux_ready') is True and receipt.get('declaration_sha256') == c['config_sha256'],
                'Flux revision not reconciled')
        require(authorization is not None and authorization.get('candidate_sha256') == fingerprint,
                'missing candidate-bound human authorization')
        require(authorization.get('actor') in policy['approvers'] and authorization.get('decision') == 'approved',
                'unapproved reviewer')
        require(authorization.get('evidence_url', '').startswith(policy['authorization_url_prefix']),
                'authorization must be retrieved from trusted review evidence')
    return {'schema': 1, 'status': 'PASS', 'stage': stage, 'candidate_sha256': fingerprint,
            'namespace': c['namespaces']['uat' if stage == 'uat' else 'sit'],
            'domain': c['domains']['uat' if stage == 'uat' else 'sit'],
            'execution': 'NOT_RUN', 'dispatch_authorized': False}


def gate(c, policy, stage, prs, receipt=None, run=None, authorization=None):
    """Live preflight never authenticates caller-provided JSON as evidence.

    No trusted retrieval adapter is wired yet. In particular, a structurally
    valid receipt, successful run JSON or human-approved boolean is insufficient.
    """
    if stage in ('merge', 'uat'):
        raise Blocked('Trusted GitHub/owner artifact retrieval adapter is not connected')
    result = _evaluate(c, policy, stage, prs, receipt, run, authorization)
    result.update(status='PLAN_VALID', evidence_kind='unverified_snapshot')
    return result


def rehearse(c, policy, stage, prs, receipt=None, run=None, authorization=None):
    """Offline contract falsification; deliberately cannot emit live PASS."""
    result = _evaluate(c, policy, stage, prs, receipt, run, authorization)
    result.update(status='REHEARSAL', evidence_kind='synthetic')
    return result
