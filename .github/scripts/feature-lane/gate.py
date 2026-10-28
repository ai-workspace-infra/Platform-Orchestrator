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


def validate_feature_tag(tag, feature_id):
    """Validate a tag against the authoritative feature ID, not by splitting hyphens.

    This is a naming check only; callers must separately authenticate the event,
    tag object, candidate and policy before authorizing any deployment.
    """
    require(isinstance(feature_id, str) and re.fullmatch(r'[a-z][a-z0-9-]{1,45}', feature_id) is not None and
            not feature_id.endswith('-'),
            'invalid feature id')
    require(isinstance(tag, str) and tag.endswith('-' + feature_id), 'tag does not match feature id')
    name = tag[:-(len(feature_id) + 1)]
    require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) is not None, 'invalid feature tag name')
    return name


def configurations(c, policy):
    rows = c.get('configurations', [])
    require(isinstance(rows, list) and len(rows) <= 32, 'invalid configuration members')
    seen = set()
    for row in rows:
        require(isinstance(row, dict), 'invalid configuration member')
        repo, pr = row.get('repository'), row.get('pr')
        require(repo in policy.get('configuration_paths', {}) and type(pr) is int and pr > 0 and
                (repo, pr) not in seen, 'foreign or duplicate configuration PR')
        seen.add((repo, pr))
        require(sha(row.get('sha')) and sha(row.get('base_sha')) and isinstance(row.get('base_ref'), str),
                'fixed configuration head/base required')
        paths = row.get('paths')
        require(isinstance(paths, dict) and 0 < len(paths) <= 64, 'bounded configuration paths required')
        for path, digest in paths.items():
            require(isinstance(path, str) and not path.startswith('/') and '..' not in path.split('/') and
                    any(path.startswith(prefix) for prefix in policy['configuration_paths'][repo]) and sha(digest, 64),
                    'configuration path outside reviewed scope or missing hash')
        if row['base_ref'] == 'main':
            require(row.get('depends_on_pr') is None, 'main configuration cannot claim stacked dependency')
        else:
            parent = next((p for p in rows if isinstance(p, dict) and p.get('repository') == repo and p.get('pr') == row.get('depends_on_pr')), None)
            require(parent is not None and parent.get('base_ref') == 'main' and parent.get('sha') == row['base_sha'],
                    'stacked configuration must bind its selected main-target parent head')
    if len(rows) > 1:
        entry = c.get('configuration_entrypoint')
        selected = next((row for row in rows if row['repository']+'#'+str(row['pr']) == entry), None)
        require(selected is not None and len(rows) == 2 and selected.get('depends_on_pr') is not None,
                'configuration stack needs one explicit entrypoint and its parent')
    return rows


def verify_configuration(row, snapshot, stage):
    require(snapshot.get('repository') == row['repository'] and snapshot.get('number') == row['pr'] and
            snapshot.get('head_repository') == row['repository'] and snapshot.get('head_sha') == row['sha'],
            'configuration PR source moved or forked')
    require(snapshot.get('base_ref') == row['base_ref'] and snapshot.get('path_hashes') == row['paths'],
            'configuration target or path content differs')
    if stage in ('sit', 'merge'):
        require(snapshot.get('state') == 'OPEN' and snapshot.get('merged') is False and snapshot.get('base_sha') == row['base_sha'],
                'configuration SIT requires current unmerged head/base')
    else:
        require(row['base_ref'] == 'main' and snapshot.get('merged') is True and sha(snapshot.get('merge_sha')) and
                snapshot.get('merged_path_hashes') == row['paths'],
                'configuration UAT requires merged main with identical accepted paths')


def validate_candidate(c, policy):
    require(isinstance(c, dict) and isinstance(policy, dict), 'missing candidate or trusted policy')
    require(c.get('schema') in (1, 2), 'unsupported candidate schema')
    feature = c.get('feature_id', '')
    require(isinstance(feature, str) and re.fullmatch(r'[a-z][a-z0-9-]{1,45}', feature) is not None, 'invalid feature id')
    task_url = c.get('task_url')
    issue_task = isinstance(task_url, str) and re.fullmatch(r'https://github.com/[^/]+/[^/]+/issues/[1-9][0-9]*', task_url)
    file_task = isinstance(task_url, str) and re.fullmatch(r'https://github.com/[^/]+/[^/]+/blob/[0-9a-f]{40}/.+', task_url)
    require(issue_task or (file_task and sha(c.get('task_sha256'), 64)), 'feature requires a tracked immutable task')
    require(c.get('target') == policy['target'], 'unapproved Dev target')
    require(c.get('environment') == 'dev', 'only a shared Dev host is eligible')
    namespaces = c.get('namespaces')
    domains = c.get('domains')
    stable = policy.get('uat_target')
    require(isinstance(namespaces, dict) and isinstance(domains, dict) and isinstance(stable, dict),
            'missing declared SIT/UAT targets')
    require(namespaces.get('sit') == 'feature-' + feature + '-sit', 'invalid temporary SIT namespace')
    if c['schema'] == 2:
        tag = c.get('feature_tag')
        validate_feature_tag(tag, feature)
        label = tag + '-sit'
        require(all(len(prefix + label) <= 63 for prefix in ('', 'accounts-', 'billing-')),
                'SIT DNS label exceeds 63 characters')
        require(domains.get('sit') == label + '.' + policy['domain_suffix'], 'unapproved temporary SIT domain')
    else:
        require(domains.get('sit') == feature + '-sit.' + policy['domain_suffix'], 'unapproved temporary SIT domain')
    require(isinstance(stable.get('namespace'), str) and bool(stable['namespace']) and
            isinstance(stable.get('domain'), str) and bool(stable['domain']), 'missing trusted stable UAT target')
    require(namespaces.get('uat') == stable['namespace'] and domains.get('uat') == stable['domain'],
            'UAT must match trusted declared stable target')
    require(namespaces['sit'] != namespaces['uat'] and domains['sit'] != domains['uat'],
            'SIT and stable UAT must be distinct')
    for field in ('chart_digest', 'config_sha256', 'data_baseline_sha256'):
        value = c.get(field)
        if field == 'chart_digest':
            require(isinstance(value, str) and value.startswith('sha256:') and sha(value[7:], 64),
                    'missing immutable ' + field)
        else:
            require(sha(value, 64), 'missing immutable ' + field)
    sources = c.get('sources', [])
    require(isinstance(sources, list) and bool(sources), 'missing participating sources')
    seen = set()
    features = 0
    for source in sources:
        require(isinstance(source, dict), 'invalid participating source')
        repo = source.get('repository')
        require(repo in policy['repositories'] and repo not in seen, 'foreign or duplicate repository')
        seen.add(repo)
        require(sha(source.get('sha')), 'source must be full SHA')
        require(isinstance(source.get('image'), str) and re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', source['image']), 'image must use digest')
        if source.get('kind') == 'feature':
            require(type(source.get('pr')) is int and source['pr'] > 0, 'feature source requires real PR')
            features += 1
        else:
            require(source.get('kind') == 'baseline' and source.get('pr') is None,
                    'baseline dependencies cannot masquerade as open feature PRs')
    configs = configurations(c, policy)
    rehearsal = c.get('candidate_mode') == 'main-rehearsal'
    if rehearsal:
        require(c['schema'] == 2 and c.get('task_url') in policy.get('main_rehearsal_tasks', []) and
                features == 0 and not configs,
                'main rehearsal must be explicitly allowed for this task and use only baseline sources')
    else:
        require(c.get('candidate_mode') in (None, 'feature') and (features > 0 or bool(configs)),
                'already merged baseline alone cannot establish premerge SIT')
    components = c.get('components')
    require((not configs and c['schema'] != 2) or components is not None,
            'candidate requires independent runtime components')
    if components is not None:
        require(isinstance(components, dict) and bool(components), 'runtime components required')
        expected = policy.get('runtime_components')
        require(isinstance(expected, dict) and set(components) == set(expected), 'runtime component set differs from policy')
        for component, item in components.items():
            require(isinstance(component, str) and isinstance(item, dict) and item.get('source_repository') == expected[component] and
                    any(source['repository'] == item.get('source_repository') and source['image'] == item.get('image') for source in sources),
                    'runtime component lacks verified image source')
    tests = c.get('required_tests')
    require(isinstance(tests, list) and all(isinstance(test, str) for test in tests) and
            set(tests) == set(policy['required_tests']), 'required acceptance contract mismatch')
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
        mapping = snapshot.get('merge_artifact')
        require(isinstance(mapping, dict), 'missing merge SHA to artifact mapping')
        require(mapping.get('merge_sha') == snapshot['merge_sha'] and mapping.get('source_sha') == source['sha'],
                'merge artifact source mismatch')
        require(mapping.get('image') == source['image'] and sha(mapping.get('manifest_sha256'), 64),
                'merge artifact differs from accepted SIT; require new candidate')
        require(sha(mapping.get('source_tree_sha')) and mapping.get('source_tree_sha') == mapping.get('merge_tree_sha'),
                'merged tree differs from accepted source; require new candidate')


def verify_run(run, expected, source_sha, event):
    require(run.get('repository') == expected['repository'] and run.get('path') == expected['workflow'],
            'foreign evidence owner')
    require(run.get('head_sha') == source_sha and run.get('event') == event, 'evidence source/event mismatch')
    require(type(run.get('id')) is int and run['id'] > 0 and
            type(run.get('attempt')) is int and run['attempt'] > 0,
            'missing or ambiguous evidence run')
    require(run.get('status') == 'completed' and run.get('conclusion') == 'success', 'evidence run not successful')


def _evaluate(c, policy, stage, prs, receipt=None, run=None, authorization=None, config_prs=None):
    fingerprint = validate_candidate(c, policy)
    require(stage in ('sit', 'merge', 'uat'), 'unsupported stage')
    for source in c['sources']:
        if source['kind'] == 'feature':
            require(source['repository'] in prs, 'missing live PR snapshot')
            verify_pr(source, prs[source['repository']], 'sit' if stage in ('sit', 'merge') else 'uat')
    for row in c.get('configurations', []):
        key = row['repository']+'#'+str(row['pr'])
        require(isinstance(config_prs, dict) and key in config_prs, 'missing configuration PR API evidence')
        verify_configuration(row, config_prs[key], stage)
    if stage in ('merge', 'uat'):
        require(receipt is not None and run is not None, 'missing structured SIT evidence')
        verify_run(run, policy['acceptance_owner'], policy['acceptance_owner']['sha'], 'workflow_dispatch')
        require(receipt.get('schema') == 1 and receipt.get('evidence_kind') == 'live', 'synthetic evidence cannot pass')
        require(type(receipt.get('run_id')) is int and type(receipt.get('run_attempt')) is int and
                receipt['run_id'] == run['id'] and receipt['run_attempt'] == run['attempt'], 'receipt/run mismatch')
        require(receipt.get('candidate_sha256') == fingerprint and receipt.get('stage') == 'sit', 'stale SIT candidate')
        require(receipt.get('target') == c['target'] and receipt.get('namespace') == c['namespaces']['sit'],
                'wrong SIT target')
        require(receipt.get('domain') == c['domains']['sit'], 'wrong SIT domain')
        images = {name: item['image'] for name, item in c['components'].items()} if c.get('components') else {s['repository']: s['image'] for s in c['sources']}
        require(receipt.get('image_ids') == images, 'runtime image mismatch')
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


def gate(c, policy=None, stage=None, prs=None, receipt=None, run=None, authorization=None, *, policy_commit=None, evidence_selectors=None):
    """Live preflight never authenticates caller-provided JSON as evidence.

    The verified path requires an explicit fixed policy_commit and retrieves all
    evidence itself. Raw receipt/run JSON or an approved boolean is insufficient.
    """
    if policy_commit is not None:
        require(all(value is None for value in (policy, prs, receipt, run, authorization)),
                'verified gate forbids caller evidence or policy JSON')
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('trusted_feature_evidence', Path(__file__).with_name('trusted.py'))
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        try:
            return adapter.verified(c, stage, policy_commit, evidence_selectors)
        except adapter.gate.Blocked as exc:
            raise Blocked(str(exc)) from None
    if stage in ('merge', 'uat'):
        raise Blocked('Trusted GitHub/owner artifact retrieval adapter requires reviewed policy_commit')
    result = _evaluate(c, policy, stage, prs, receipt, run, authorization)
    result.update(status='PLAN_VALID', evidence_kind='unverified_snapshot')
    return result


def rehearse(c, policy, stage, prs, receipt=None, run=None, authorization=None, config_prs=None):
    """Offline contract falsification; deliberately cannot emit live PASS."""
    result = _evaluate(c, policy, stage, prs, receipt, run, authorization, config_prs)
    result.update(status='REHEARSAL', evidence_kind='synthetic')
    return result
