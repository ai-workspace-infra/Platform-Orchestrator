#!/usr/bin/env python3
"""Resolve the IaC summary associated with the reviewed V6 bootstrap run."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location('migration_matrix', ROOT / '.github/scripts/acceptance/migration_matrix.py')
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)
VERIFY_SPEC = importlib.util.spec_from_file_location('workflow_artifact_provenance', ROOT / '.github/scripts/platform-ops/evidence/workflow_artifact_provenance.py')
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)
REPO = 'ai-workspace-infra/Platform-Orchestrator'
RUN = 40851581630
PARENT = 40851530314
ATTEMPT = 1
ARTIFACT = 12887850662
NAME = 'iac-summary-40851581630-1'
ARCHIVE_SHA = 'sha256:7c9486443e2dd049c0613e4457a327a239fbafc7011dffb7675ed8dceb0cfbbb'
SUMMARY_SHA = '27acdd2361d3696e520db1bd6c8e5ae26aece2dc57321edec5f4f821a7d3cebd'
INVENTORY_SHA = 'e6ebb64a8fa179b0e3c2543635f45c70e7161ef7e0028b0ba0a5b0cccb5d673f'
WORKFLOW_SHA = '1b73eb3d07791d38e1af9d6d50964ff72181fac6'
GITOPS_SHA = 'c74a1a5a7d3a633d4020897fbb765b3e23fb279a'
IAC_SHA = 'adf9c140cd2c120361012917cddcde1e58876c6c'


def resolve(api=MATRIX.api, artifact_file=MATRIX.artifact_file):
    spec = {'repository': REPO, 'run_id': RUN, 'attempt': ATTEMPT,
            'workflow': '.github/workflows/iac-orchestrator.yml', 'event': 'workflow_dispatch',
            'ref': 'v6.0.0-bootstrap.4', 'commit': WORKFLOW_SHA, 'artifact_id': ARTIFACT,
            'artifact_name': NAME, 'artifact_digest': ARCHIVE_SHA,
            'filename': 'summary.json', 'file_sha256': SUMMARY_SHA}
    raw = VERIFY.verify_artifact(api, artifact_file, spec)
    inventory = VERIFY.verify_artifact(api, artifact_file,
                                       {**spec, 'filename': 'inventory.json', 'file_sha256': INVENTORY_SHA})
    try:
        summary = json.loads(raw)
        c = summary['context']
        if (summary['result'] != 'applied_verified' or c['action'] != 'apply'
                or c['environment'] != 'prod' or c['gitops_sha'] != GITOPS_SHA
                or c['iac_sha'] != IAC_SHA or str(c['run_id']) != str(RUN)
                or str(c['run_attempt']) != str(ATTEMPT)
                or c['correlation_id'] != f'{PARENT}:1:prod-k3s-v6'
                or c['manifest_path'] != 'iac/targets/prod-akamai-k3s-v6.yaml'):
            raise ValueError('IaC summary context mismatch')
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('invalid IaC summary') from None
    return raw, inventory, {'run_id': RUN, 'artifact_id': ARTIFACT, 'archive_sha256': ARCHIVE_SHA,
                 'summary_sha256': SUMMARY_SHA, 'inventory_sha256': INVENTORY_SHA, 'iac_sha': IAC_SHA,
                 'bootstrap_gitops_sha': GITOPS_SHA}
