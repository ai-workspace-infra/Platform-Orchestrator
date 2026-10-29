#!/usr/bin/env python3
"""Resolve a fixed reviewed operation and materialize provenance-verified inputs."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import resolve_workload_identity as resolver
import verify_workload_identity_evidence as evidence


def prepare(checkout, operation_path, commit, output_root, verify=evidence.verify):
    root=Path(checkout).resolve()
    if not re.fullmatch(r'[0-9a-f]{40}',commit or ''):raise ValueError('immutable GitOps commit required')
    env={k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL') if k in os.environ}
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True,env=env).strip()
    dirty=subprocess.check_output(['git','-C',str(root),'status','--porcelain','--untracked-files=all'],text=True,env=env).strip()
    if head!=commit or dirty:raise ValueError('GitOps checkout is not the clean selected commit')
    spec=resolver.load(root,operation_path)
    checked=verify(spec)
    destination=Path(output_root)/'workload-identity-inputs'
    destination.mkdir(mode=0o700,parents=False,exist_ok=False)
    for name,key in (('bootstrap.json','bootstrap'),('summary.json','summary'),('inventory.json','inventory')):
        fd=os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(checked[key])
    return {'directory':str(destination),'operation_path':operation_path,'gitops_sha':commit,
            'bootstrap_sha256':checked['bootstrap_sha256'],'summary_sha256':checked['summary_sha256'],
            'bootstrap_gitops_sha':spec['evidence']['bootstrap']['gitopsSha'],
            'iac_sha':spec['evidence']['iac']['iacSha'],'iac_target_manifest':spec['target']['iacTargetManifest'],
            'iac_run_id':str(spec['evidence']['iac']['runId']),'iac_attempt':str(spec['evidence']['iac']['attempt']),
            'iac_correlation_id':spec['evidence']['iac']['correlationId'],
            'environment':spec['environment'],'provider':spec['target']['provider'],'account':spec['target']['account'],
            'node':spec['target']['node'],'vault_address':spec['vault']['address'],
            'access_role':spec['vault']['accessRole'],'admin_role':spec['vault']['adminRole'],
            'ssh_key_path':spec['vault']['sshKeyPath'],'ssh_key_field':spec['vault']['sshKeyField'],
            'provider_token_path':spec['vault']['providerTokenPath'],'provider_token_field':spec['vault']['providerTokenField']}


def main():
    result=prepare(os.environ['IDENTITY_GITOPS'],os.environ['IDENTITY_OPERATION'],os.environ['IDENTITY_GITOPS_SHA'],os.environ['RUNNER_TEMP'])
    with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as output:
        for key,value in result.items():
            if any(c in str(value) for c in '\r\n'):raise ValueError('invalid output value')
            output.write(key+'='+str(value)+'\n')
    print('WORKLOAD_IDENTITY_PROVENANCE_VERIFIED')


if __name__=='__main__':
    try:main()
    except (KeyError,TypeError,ValueError,OSError,subprocess.SubprocessError):
        raise SystemExit('workload identity preparation failed') from None
