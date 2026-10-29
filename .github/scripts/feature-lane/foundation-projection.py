#!/usr/bin/env python3
"""Project reviewed foundation evidence for the same protected Feature run."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def project(policy, receipt, env, resolver, reader):
    repo = env.get('GITHUB_REPOSITORY', '')
    source = receipt.get('source', {})
    expected_ref = repo + '/.github/workflows/feature-lane-deploy.yml@refs/heads/main'
    if (repo != 'ai-workspace-infra/Platform-Orchestrator' or env.get('GITHUB_REF') != 'refs/heads/main' or
        env.get('GITHUB_WORKFLOW_REF') != expected_ref or source.get('repository') != repo or
        source.get('workflow_ref') != expected_ref or source.get('workflow_sha') != env.get('GITHUB_SHA') or
        source.get('run_id') != env.get('GITHUB_RUN_ID') or source.get('run_attempt') != env.get('GITHUB_RUN_ATTEMPT') or
        receipt.get('schema_version') != 'dev-feature-candidate/v2' or receipt.get('result') != 'verified' or
        receipt.get('stage') != 'sit' or not re.fullmatch(r'[0-9a-f]{64}', str(receipt.get('candidate_sha256', '')))):
        raise ValueError('same-run verified SIT candidate required')
    locator = policy.get('sit_foundation')
    if not isinstance(locator, dict) or set(locator) != {'run_id', 'summary_artifact_id', 'bootstrap_artifact_id'}:
        raise ValueError('reviewed SIT foundation locator required')
    raw, identity = resolver.foundation(reader, locator['run_id'], locator['summary_artifact_id'], locator['bootstrap_artifact_id'])
    if hashlib.sha256(raw.encode()).hexdigest() != identity['cmdb_sha256']:
        raise ValueError('foundation CMDB digest mismatch')
    return raw, identity

def main():
    env = os.environ
    trusted = load('feature_trusted', ROOT / '.github/scripts/feature-lane/trusted.py')
    resolver = load('dev_feature_foundation', ROOT / '.github/actions/dev-feature-resolve/resolve.py')
    receipt = json.loads(Path(env['FEATURE_RECEIPT_FILE']).read_text())
    raw, identity = project(trusted.policy_at(env['GITHUB_SHA']), receipt, env, resolver, trusted.reader)
    destination = Path(env['RUNNER_TEMP']) / 'feature-foundation'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'cmdb.json').write_text(raw)
    (destination / 'foundation.json').write_text(json.dumps(identity, sort_keys=True) + '\n')
    with Path(env['GITHUB_OUTPUT']).open('a') as output:
        for key in ('instance_id', 'cmdb_sha256', 'node_uid', 'cluster_uid', 'platform_sha'):
            value = str(identity[key])
            if not re.fullmatch(r'[A-Za-z0-9-]+', value):
                raise ValueError('invalid foundation output')
            output.write(f'{key}={value}\n')
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('::error::Reviewed SIT foundation could not be authenticated', file=sys.stderr)
        sys.exit(1)
