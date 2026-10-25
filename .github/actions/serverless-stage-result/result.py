#!/usr/bin/env python3
"""Collect non-secret results within one reusable-workflow run; never execute a target."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

STAGES = {
    'resolve': ('preflight',),
    'infra': ('iac', 'iac-verified', 'destroy'),
    'deploy': ('supabase', 'init_schema', 'uat_accounts_schema_probe', 'uat_accounts_baseline',
               'uat_accounts_schema_migration', 'cloud_run', 'artifact_manifest', 'backend_gate',
               'cloudflare_ssr', 'frontend_router', 'edge_gateway', 'static_pages',
               'serverless_domains_provider', 'serverless_domains'),
    'migrate': ('trigger_data_migration', 'stripe_catalog'),
    'verify': ('verify', 'console_release_metadata'),
}
DEPLOY_PHASES = {
    'data': STAGES['deploy'][:5],
    'backend': ('cloud_run', 'artifact_manifest', 'backend_gate'),
    'frontend': ('cloudflare_ssr', 'frontend_router', 'edge_gateway', 'static_pages'),
    'domains': ('serverless_domains_provider', 'serverless_domains'),
}
STAGES.update(DEPLOY_PHASES)
OUTPUTS = {
    'preflight': ('gitops_ref', 'guarded_api_gateway', 'target_manifest', 'iac_sha', 'selectors'),
    'supabase': ('data_run_id',),
}
RESULTS = {'success', 'failure', 'cancelled', 'skipped'}
PARENTS = ('resolve', 'infrastructure', 'deploy', 'migrate')


def sanitize(results: dict, expected) -> dict:
    if not isinstance(results, dict) or set(results) != set(expected):
        raise ValueError('Stage dependency map does not match the approved stage jobs')
    clean = {}
    for name in expected:
        value = results[name]
        if not isinstance(value, dict) or value.get('result') not in RESULTS:
            raise ValueError(f'Invalid result for {name}')
        outputs = value.get('outputs', {})
        if not isinstance(outputs, dict):
            raise ValueError(f'Invalid outputs for {name}')
        selected = {key: outputs[key] for key in OUTPUTS.get(name, ()) if key in outputs}
        if not all(isinstance(value, str) for value in selected.values()):
            raise ValueError(f'Non-string control-plane output for {name}')
        clean[name] = {'result': value['result'], 'outputs': selected}
    return clean


def metadata() -> None:
    contexts = json.loads(os.environ['STAGE_CONTEXTS'])
    lanes = {}
    for stage in ('resolve', 'infra', 'deploy', 'migrate'):
        expected = STAGES[stage]
        if stage == 'verify':
            continue
        value = json.loads(contexts.get(f'{stage}_context', '{}'))
        # A failed reusable workflow can omit its outputs. The parent stage
        # conclusion below still records and rejects that failure.
        if value:
            lanes.update({name: {'result': job['result']}
                          for name, job in sanitize(value, expected).items()})
    lanes['verify'] = {'result': os.environ['VERIFY_RESULT']}
    parents = sanitize(json.loads(os.environ['STAGE_RESULTS']), PARENTS)
    document = {
        'environment': os.environ['RELEASE_ENV'], 'tag': os.environ['RELEASE_TAG'],
        'operation': os.environ['RELEASE_OPERATION'], 'target': os.environ['RELEASE_TARGET'],
        'lanes': lanes,
        'stages': {name: {'result': job['result']} for name, job in parents.items()},
    }
    Path('release-metadata.json').write_text(json.dumps(document) + '\n')


def main() -> None:
    stage = os.environ['SERVERLESS_STAGE']
    if stage not in STAGES:
        raise ValueError('Unknown serverless stage')
    raw = json.loads(os.environ['STAGE_JOBS'])
    group_failures = []
    if stage == 'deploy':
        phases = sanitize(raw, DEPLOY_PHASES)
        clean = {}
        for name, phase in phases.items():
            value = raw[name].get('outputs', {}).get('context', '')
            if phase['result'] == 'success':
                if not value:
                    raise ValueError(f'Missing successful phase context: {name}')
                clean.update(sanitize(json.loads(value), DEPLOY_PHASES[name]))
            else:
                group_failures.append(f'phase:{name}')
                # A failed reusable workflow can omit its outputs; never turn
                # that into a successful phase or invent successful lanes.
                clean.update({job: {'result': phase['result'], 'outputs': {}}
                              for job in DEPLOY_PHASES[name]})
        clean = sanitize(clean, STAGES['deploy'])
    else:
        clean = sanitize(raw, STAGES[stage])
    prior = json.loads(os.environ.get('STAGE_RESULTS', '{}'))
    if stage == 'verify':
        prior = sanitize(prior, PARENTS)
    elif prior:
        raise ValueError('Only Verify may consume the parent stage results')
    run_id = os.environ['GITHUB_RUN_ID']
    attempt = os.environ['GITHUB_RUN_ATTEMPT']
    if not (run_id.isascii() and run_id.isdecimal() and int(run_id) > 0 and
            attempt.isascii() and attempt.isdecimal() and int(attempt) > 0):
        raise ValueError('Invalid run identity')
    context = json.dumps(clean, separators=(',', ':'))
    path = Path(os.environ['RUNNER_TEMP']) / f'serverless-stage-{stage}.json'
    path.write_text(json.dumps({'schema': 1, 'stage': stage, 'run_id': run_id,
                               'run_attempt': attempt, 'context': clean}) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'context={context}\nresult_file={path}\n')
    failures = group_failures + [name for name, value in clean.items() if value['result'] in {'failure', 'cancelled'}]
    failures.extend(f'parent:{name}' for name, value in prior.items() if value['result'] != 'success')
    with open(os.environ.get('GITHUB_STEP_SUMMARY', os.devnull), 'a') as summary:
        summary.write(f'### Serverless {stage}\n\n')
        for name, value in clean.items():
            summary.write(f'- {name}: {value["result"]}\n')
    if failures:
        raise ValueError('Stage completion rejected: ' + ', '.join(failures))
    print(f'Serverless {stage}: current-run dependencies accepted')


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['metadata']:
            metadata()
        elif not sys.argv[1:]:
            main()
        else:
            raise ValueError('Unsupported command')
    except (ValueError, KeyError, TypeError) as error:
        print(f'::error::{error}', file=sys.stderr)
        sys.exit(1)
