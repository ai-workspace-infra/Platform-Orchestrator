#!/usr/bin/env python3
"""Project DNS inputs exclusively from a verified same-run candidate receipt."""
import json
import os
from pathlib import Path
import re
import sys

def project(receipt, env):
    repo = env.get('GITHUB_REPOSITORY', '')
    ref = repo + '/.github/workflows/feature-lane-deploy.yml@refs/heads/main'
    if not isinstance(receipt,dict): raise ValueError('receipt missing')
    source = receipt.get('source', {})
    lane = receipt.get('projection', {}).get('tagged_lane', {})
    feature, tag = lane.get('feature_id', ''), lane.get('feature_tag', '')
    fingerprint = receipt.get('candidate_sha256', '')
    gitops_sha = receipt.get('candidate_head', '')
    if (repo != 'ai-workspace-infra/Platform-Orchestrator' or env.get('GITHUB_REF') != 'refs/heads/main' or
        env.get('GITHUB_WORKFLOW_REF') != ref or receipt.get('schema_version') != 'dev-feature-candidate/v2' or
        receipt.get('result') != 'verified' or receipt.get('stage') != 'sit' or receipt.get('repository') != 'ai-workspace-infra/gitops' or
        source.get('repository') != repo or source.get('workflow_ref') != ref or source.get('workflow_sha') != env.get('GITHUB_SHA') or
        source.get('run_id') != env.get('GITHUB_RUN_ID') or source.get('run_attempt') != env.get('GITHUB_RUN_ATTEMPT') or
        not re.fullmatch(r'[0-9a-f]{40}', str(gitops_sha)) or not re.fullmatch(r'[0-9a-f]{64}', str(fingerprint)) or
        lane.get('candidate_sha256') != fingerprint or not re.fullmatch(r'[a-z][a-z0-9-]{1,45}', str(feature)) or
        feature.endswith('-') or not isinstance(tag,str) or not tag.endswith('-'+feature) or
        not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', tag) or len('accounts-'+tag+'-sit') > 63):
        raise ValueError('untrusted DNS candidate projection')
    return {'feature_id':feature, 'feature_tag':tag, 'candidate_sha256':fingerprint, 'gitops_sha':gitops_sha,
            'console_host':tag+'-sit.onwalk.net', 'accounts_host':'accounts-'+tag+'-sit.onwalk.net',
            'billing_host':'billing-'+tag+'-sit.onwalk.net'}

if __name__ == '__main__':
    try:
        result=project(json.loads(Path(os.environ['FEATURE_RECEIPT_FILE']).read_text()),os.environ)
        with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
            for key,value in result.items(): output.write(f'{key}={value}\n')
    except Exception:
        print('::error::Feature DNS input projection rejected',file=sys.stderr)
        sys.exit(1)
