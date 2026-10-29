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
REPO = 'ai-workspace-infra/Platform-Orchestrator'
RUN = 40851581630
PARENT = 40851530314
ATTEMPT = 1
ARTIFACT = 12887850662
NAME = 'iac-summary-40851581630-1'
ARCHIVE_SHA = 'sha256:7c9486443e2dd049c0613e4457a327a239fbafc7011dffb7675ed8dceb0cfbbb'
SUMMARY_SHA = '27acdd2361d3696e520db1bd6c8e5ae26aece2dc57321edec5f4f821a7d3cebd'
WORKFLOW_SHA = '1b73eb3d07791d38e1af9d6d50964ff72181fac6'
GITOPS_SHA = 'c74a1a5a7d3a633d4020897fbb765b3e23fb279a'
IAC_SHA = 'adf9c140cd2c120361012917cddcde1e58876c6c'


def resolve(api=MATRIX.api, artifact_file=MATRIX.artifact_file):
    run = api(f'repos/{REPO}/actions/runs/{RUN}')
    artifact = api(f'repos/{REPO}/actions/artifacts/{ARTIFACT}')
    if (run.get('id') != RUN or run.get('run_attempt') != ATTEMPT
            or run.get('repository', {}).get('full_name') != REPO
            or run.get('event') != 'workflow_dispatch'
            or run.get('path') != '.github/workflows/iac-orchestrator.yml'
            or run.get('head_branch') != 'v6.0.0-bootstrap.4'
            or run.get('head_sha') != WORKFLOW_SHA or run.get('status') != 'completed'
            or run.get('conclusion') != 'success'):
        raise ValueError('IaC run provenance mismatch')
    if (artifact.get('id') != ARTIFACT or artifact.get('name') != NAME
            or artifact.get('digest') != ARCHIVE_SHA or artifact.get('expired') is not False
            or artifact.get('workflow_run', {}).get('id') != RUN
            or artifact.get('workflow_run', {}).get('head_sha') != WORKFLOW_SHA):
        raise ValueError('IaC artifact provenance mismatch')
    raw = artifact_file(REPO, ARTIFACT, RUN, ATTEMPT, NAME, 'summary.json', WORKFLOW_SHA)
    if hashlib.sha256(raw).hexdigest() != SUMMARY_SHA:
        raise ValueError('IaC summary digest mismatch')
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
    return raw, {'run_id': RUN, 'artifact_id': ARTIFACT, 'archive_sha256': ARCHIVE_SHA,
                 'summary_sha256': SUMMARY_SHA, 'iac_sha': IAC_SHA,
                 'bootstrap_gitops_sha': GITOPS_SHA}
