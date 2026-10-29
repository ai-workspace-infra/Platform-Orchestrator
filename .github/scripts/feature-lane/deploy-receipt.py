#!/usr/bin/env python3
"""Generate a same-run receipt after fresh trusted verification; never deploy."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_receipt(candidate, selectors, env, gate):
    repo = env.get('GITHUB_REPOSITORY', '')
    ref = env.get('GITHUB_WORKFLOW_REF', '')
    sha = env.get('GITHUB_SHA', '')
    run = env.get('GITHUB_RUN_ID', '')
    attempt = env.get('GITHUB_RUN_ATTEMPT', '')
    if (repo not in ('ai-workspace-infra/platform-ops-toolkit', 'ai-workspace-infra/Platform-Orchestrator') or
        ref != repo + '/.github/workflows/feature-lane-deploy.yml@refs/heads/main' or
        env.get('GITHUB_REF') != 'refs/heads/main' or not gate.sha(sha) or
        not re.fullmatch(r'[1-9][0-9]*', run) or not re.fullmatch(r'[1-9][0-9]*', attempt)):
        raise ValueError('protected Main deployment workflow context required')
    result = gate.gate(candidate, stage='sit', policy_commit=sha, evidence_selectors=selectors)
    projection = result.get('verified_projection')
    if (result.get('status') != 'VERIFIED_GATE' or result.get('dispatch_authorized') is not False or
        result.get('execution') != 'NOT_RUN' or result.get('candidate_sha256') != gate.identity(candidate) or
        not isinstance(projection, dict) or projection.get('tagged_lane', {}).get('candidate_sha256') != result['candidate_sha256'] or
        candidate.get('gitops', {}).get('repository') != 'ai-workspace-infra/gitops' or
        not gate.sha(candidate.get('gitops', {}).get('sha'))):
        raise ValueError('fresh candidate verification required')
    if (set(projection) != {'tagged_lane', 'chart_digest', 'knowledge', 'components'} or
        projection['tagged_lane'] != {'feature_id': candidate.get('feature_id'),
                                      'feature_tag': candidate.get('feature_tag'),
                                      'candidate_sha256': result['candidate_sha256']} or
        projection['chart_digest'] != candidate.get('chart_digest') or
        not isinstance(projection['knowledge'], dict) or
        set(projection['knowledge']) != {'repository', 'sha'} or
        projection['knowledge']['repository'] != 'ai-workspace-services/knowledge' or
        not gate.sha(projection['knowledge']['sha']) or
        not isinstance(projection['components'], dict) or
        set(projection['components']) != {'caddy', 'postgresql', 'console', 'accounts', 'billing', 'content'} or
        projection['components'] != result.get('verified_runtime_components') or
        projection['chart_digest'] != result.get('verified_chart_digest') or
        not isinstance(result.get('verified_data_baseline'), dict) or
        result['verified_data_baseline'].get('sha256') != candidate.get('data_baseline_sha256') or
        not gate.sha(candidate.get('data_baseline_sha256'), 64) or
        projection['knowledge'] != {key: result.get('verified_website_content', {}).get(key) for key in ('repository', 'sha')}):
        raise ValueError('incomplete or inconsistent deployment projection')
    baseline = result['verified_data_baseline']
    inputs = baseline.get('inputs')
    if (not isinstance(inputs, dict) or
        hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != candidate['data_baseline_sha256']):
        raise ValueError('verified data baseline inputs missing or changed')
    return {'schema_version': 'dev-feature-candidate/v2', 'result': 'verified',
            'repository': 'ai-workspace-infra/gitops', 'stage': 'sit',
            'candidate_head': candidate['gitops']['sha'], 'candidate_sha256': result['candidate_sha256'],
            'data_baseline_sha256': candidate['data_baseline_sha256'],
            'data_baseline_inputs': inputs,
            'source': {'repository': repo, 'workflow_ref': ref, 'workflow_sha': sha,
                       'run_id': run, 'run_attempt': attempt}, 'projection': projection}


def failure_message(error):
    # Only predefined messages may reach the public workflow log. Never emit
    # arbitrary exception text, which can contain API response or credential data.
    known = {
        'rehearsal Main moved or unavailable': 'A rehearsal source Main moved or could not be read; revalidate and freeze a new candidate.',
        'configuration SIT requires current unmerged head/base': 'The configuration PR is no longer the fixed unmerged head and base; freeze a new candidate.',
        'PR Main base moved; require new candidate': 'A feature PR Main base moved; freeze a new candidate.',
    }
    return known.get(str(error), 'Feature deployment receipt verification failed')


def main():
    try:
        preflight = load('feature_preflight', HERE / 'preflight.py')
        gate = load('feature_gate', HERE / 'gate.py')
        candidate = preflight.read_json(os.environ['FEATURE_CANDIDATE_FILE'])
        selectors = preflight.read_json(os.environ['FEATURE_EVIDENCE_SELECTORS_FILE'])
        receipt = build_receipt(candidate, selectors, os.environ, gate)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (KeyError, OSError, ValueError, TypeError) as error:
        print('::error::' + failure_message(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
