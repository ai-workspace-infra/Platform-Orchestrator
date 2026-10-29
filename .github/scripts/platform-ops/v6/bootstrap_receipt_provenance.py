#!/usr/bin/env python3
"""Control-plane validation for the reviewed V6 bootstrap receipt.

Only the exact previously reviewed successful run and artifact are accepted.
This module is not a deploy entry point and performs no host or Vault operation.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location('migration_matrix', ROOT / '.github/scripts/acceptance/migration_matrix.py')
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)
VERIFY_SPEC = importlib.util.spec_from_file_location('workflow_artifact_provenance', ROOT / '.github/scripts/platform-ops/evidence/workflow_artifact_provenance.py')
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)

REPO = 'ai-workspace-infra/Platform-Orchestrator'
RUN_ID = 40851530314
ATTEMPT = 1
ARTIFACT_ID = 12887223723
ARTIFACT_NAME = 'prod-k3s-v6-bootstrap-40851530314-1'
ARTIFACT_DIGEST = 'sha256:167f7650702f20c99b852c88697c433f93dd65a258f2a8bfef3afecb5903395f'
RECEIPT_SHA256 = 'fd9bde1650d637b56415b860b33955b336c79b04f456254eea2c3063c34d6c06'
TAG = 'v6.0.0-bootstrap.4'
WORKFLOW_SHA = '1b73eb3d07791d38e1af9d6d50964ff72181fac6'
GITOPS_SHA = 'c74a1a5a7d3a633d4020897fbb765b3e23fb279a'


def resolve(api=MATRIX.api, artifact_file=MATRIX.artifact_file):
    tag = api(f'repos/{REPO}/commits/{TAG}')
    if tag.get('sha') != WORKFLOW_SHA:
        raise ValueError('bootstrap tag provenance mismatch')
    raw = VERIFY.verify_artifact(api, artifact_file, {
        'repository': REPO, 'run_id': RUN_ID, 'attempt': ATTEMPT,
        'workflow': '.github/workflows/selfhost-orchestrator.yml', 'event': 'workflow_dispatch',
        'ref': TAG, 'commit': WORKFLOW_SHA, 'artifact_id': ARTIFACT_ID,
        'artifact_name': ARTIFACT_NAME, 'artifact_digest': ARTIFACT_DIGEST,
        'filename': 'v6-bootstrap-receipt.json', 'file_sha256': RECEIPT_SHA256})
    try:
        data = json.loads(raw)
        if (data['result'] != 'PAUSED_BOOTSTRAP_VERIFIED' or data['node'] != 'prod-k3s-v6'
                or data['version'] != 'v1.37.1+k3s1' or data['gitops_sha'] != GITOPS_SHA
                or data['common']['result'] != 'COMMON_NODE_VERIFIED'
                or data['common']['node'] != 'prod-k3s-v6'
                or data['audit']['result'] != 'AUDIT_ALLOW_DENY_VERIFIED'):
            raise ValueError('bootstrap receipt validation failed')
        for name in ('node_uid', 'cluster_uid'):
            if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', data[name]):
                raise ValueError('bootstrap identity invalid')
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('invalid bootstrap receipt') from None
    return raw, {'run_id': RUN_ID, 'attempt': ATTEMPT, 'artifact_id': ARTIFACT_ID,
                 'artifact_digest': ARTIFACT_DIGEST, 'receipt_sha256': RECEIPT_SHA256,
                 'workflow_sha': WORKFLOW_SHA, 'bootstrap_gitops_sha': GITOPS_SHA}
