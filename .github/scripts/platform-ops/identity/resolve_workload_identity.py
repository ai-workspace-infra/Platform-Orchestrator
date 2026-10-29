#!/usr/bin/env python3
"""Validate a reviewed GitOps workload identity operation declaration."""
from pathlib import Path
from urllib.parse import urlsplit
import json
import re
import yaml


class ContractError(ValueError):
    pass


def validate(document):
    if not isinstance(document,dict) or document.get('apiVersion')!='operations.svc.plus/v1alpha1' or document.get('kind')!='VaultWorkloadIdentityOperation':
        raise ContractError('unexpected identity declaration type')
    try:
        spec=document['spec'];target=spec['target'];vault=spec['vault'];identity=spec['identity'];evidence=spec['evidence']
        if spec['environment'] not in {'sit','uat','prod'} or target['runtime'] not in {'k3s','kubernetes'}:
            raise ContractError('unsupported environment or runtime')
        name=r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?'
        for v in (target['node'],identity['mount'],identity['role'],identity['policy'],identity['namespace'],identity['serviceAccount'],identity['probeServiceAccount']):
            if not isinstance(v,str) or not re.fullmatch(name,v) or len(v)>63:raise ContractError('invalid identity or node name')
        for field in ('provider','account','sshUser'):
            if not isinstance(target[field],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',target[field]):
                raise ContractError('invalid target selector')
        if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+[+A-Za-z0-9.-]*',target['kubernetesVersion']):
            raise ContractError('explicit Kubernetes version required')
        for field in ('accessRole','adminRole','adminPolicy'):
            if not isinstance(vault[field],str) or not re.fullmatch(name,vault[field]) or len(vault[field])>128:
                raise ContractError('invalid Vault role or policy')
        for field in ('sshKeyField','providerTokenField'):
            if not isinstance(vault[field],str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',vault[field]):
                raise ContractError('invalid secret field')
        for field in ('audience','deniedAudience'):
            if not isinstance(identity[field],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}',identity[field]):
                raise ContractError('invalid workload audience')
        if identity['serviceAccount']==identity['probeServiceAccount'] or identity['audience']==identity['deniedAudience'] or identity['allowedPath']==identity['deniedPath']:
            raise ContractError('authorization probes must be distinct')
        for p in (identity['allowedPath'],identity['deniedPath'],vault['sshKeyPath'],vault['providerTokenPath']):
            if not isinstance(p,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*',p) or '..' in p.split('/'):
                raise ContractError('exact safe paths required')
        if type(identity['ttlSeconds']) is not int or not 0 < identity['ttlSeconds'] <= 600:raise ContractError('invalid identity TTL')
        address=urlsplit(vault['address'])
        if address.scheme!='https' or not address.hostname or address.username or address.password or address.path not in ('','/') or address.query or address.fragment:
            raise ContractError('HTTPS Vault endpoint required')
        for path in (target['declaration'],target['iacTargetManifest']):
            if not isinstance(path,str) or not path.endswith('.yaml') or Path(path).is_absolute() or '..' in Path(path).parts:
                raise ContractError('invalid declaration path')
        for part in ('bootstrap','iac'):
            row=evidence[part]
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',row['repository']) or not re.fullmatch(r'v[0-9][A-Za-z0-9.+-]*',row['ref']):
                raise ContractError('reviewed repository and stable tag required')
            if row['event'] != 'workflow_dispatch' or not re.fullmatch(r'\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml',row['workflow']):
                raise ContractError('reviewed workflow dispatch required')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+',row['artifactName']) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.json',row['filename']):
                raise ContractError('invalid artifact identity')
            for key in ('runId','attempt','artifactId'):
                if type(row[key]) is not int or row[key] <= 0:raise ContractError('invalid evidence identifier')
            for key in ('commit','gitopsSha' if part=='bootstrap' else 'iacSha'):
                if not re.fullmatch(r'[0-9a-f]{40}',row[key]):raise ContractError('immutable commit required')
            if not re.fullmatch(r'sha256:[0-9a-f]{64}',row['artifactDigest']) or not re.fullmatch(r'[0-9a-f]{64}',row['fileSha256']):
                raise ContractError('immutable artifact digest required')
        if not re.fullmatch(r'[0-9a-f]{64}',evidence['iac']['inventorySha256']):raise ContractError('inventory digest required')
        return spec
    except (KeyError,TypeError):
        raise ContractError('missing identity declaration field') from None


def load(checkout, relative):
    root=Path(checkout).resolve();target=(root/relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():raise ContractError('declaration outside checkout')
    return validate(yaml.safe_load(target.read_text()))
