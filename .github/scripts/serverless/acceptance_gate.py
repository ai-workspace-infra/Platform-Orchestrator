#!/usr/bin/env python3
"""Control-plane admission/summary only; no resource or service execution.

The current entry contains unimplemented execution steps. Keep mutations closed
until a reviewed owner cutover replaces this gate and supplies runtime evidence.
"""
import json
import os
from pathlib import Path
import sys

STAGES = ('prepare', 'database', 'backend', 'frontend', 'configure')
OPERATIONS = ('plan', 'init', 'deploy', 'upgrade', 'migrate', 'deploy+migrate')


def admit(environment, operation, dns_mode):
    if environment not in ('uat', 'prod') or operation not in OPERATIONS:
        raise ValueError('Unsupported environment or operation')
    if dns_mode not in ('none', 'uat-records', 'prod-cutover'):
        raise ValueError('Unsupported DNS mode')
    if operation != 'plan':
        raise ValueError('Release blocked: database initialization, application deployment, '
                         'DNS and runtime health owner execution are not fully wired; '
                         'placeholder success is not acceptance. See issue #1445.')
    if dns_mode != 'none':
        raise ValueError('Plan must use dns_mode=none; DNS mutation is forbidden')


def receipt(stages, environment, operation, tag, run_id, attempt, sha):
    if environment not in ('uat', 'prod') or operation not in OPERATIONS:
        raise ValueError('Unsupported receipt environment or operation')
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        raise ValueError('Missing or unexpected stage results')
    for value in (run_id, attempt):
        if not value.isascii() or not value.isdecimal() or int(value) < 1:
            raise ValueError('Invalid run identity')
    if len(sha) != 40 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('Invalid workflow source SHA')
    results = {}
    for stage in STAGES:
        data = stages[stage]
        if not isinstance(data, dict) or data.get('result') not in ('success', 'failure', 'cancelled', 'skipped'):
            raise ValueError('Invalid stage result: ' + stage)
        results[stage] = {'result': data['result']}
    plan_only = (operation == 'plan' and results['prepare']['result'] == 'success'
                 and all(results[name]['result'] == 'skipped' for name in STAGES[1:]))
    return {
        'schema': 1, 'pipeline': 'serverless-orchestrator', 'environment': environment,
        'operation': operation, 'release_tag': tag, 'run_id': run_id,
        'run_attempt': attempt, 'workflow_sha': sha, 'stages': results,
        'overall_status': 'PLAN_ONLY' if plan_only else 'BLOCKED',
        'release_accepted': False, 'runtime_acceptance': 'NOT_RUN',
        'reason': ('Plan validation only; no deployment or runtime acceptance.' if plan_only else
                   'Execution owner cutover and verified runtime receipts are required; job success is insufficient.'),
    }


def main():
    environment = os.environ['ENV_TARGET']
    operation = os.environ['OP_TARGET']
    if sys.argv[1:] == ['admit']:
        admit(environment, operation, os.environ.get('DNS_MODE', 'none'))
        return
    if sys.argv[1:] != ['summary']:
        raise ValueError('Expected admit or summary')
    document = receipt(json.loads(os.environ['STAGE_RESULTS']), environment, operation,
                       os.environ.get('TAG_REF', ''), os.environ['GITHUB_RUN_ID'],
                       os.environ['GITHUB_RUN_ATTEMPT'], os.environ['GITHUB_SHA'])
    Path('serverless-delivery-receipt.json').write_text(json.dumps(document, indent=2) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('delivery_receipt=' + json.dumps(document) + '\n')
    with open(os.environ.get('GITHUB_STEP_SUMMARY', os.devnull), 'a') as summary:
        summary.write('## Serverless acceptance\n\n**' + document['overall_status'] + '**\n\n'
                      + document['reason'] + '\n\nRuntime acceptance: NOT_RUN.\n')
    if document['overall_status'] == 'BLOCKED':
        raise ValueError(document['reason'])


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError) as error:
        print(f'::error::{error}', file=sys.stderr)
        sys.exit(1)
