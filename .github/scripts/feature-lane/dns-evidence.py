#!/usr/bin/env python3
"""Validate all same-run DNS owner receipts before later SIT steps."""
import hashlib
import json
import os
from pathlib import Path
import sys

def verify(root, feature, tag, candidate, cmdb, instance, hosts):
    result={}
    for service in ('console','accounts','billing'):
        path=root/service/'receipt.json'
        if path.is_symlink() or not path.is_file() or path.stat().st_size>100000: raise ValueError('DNS receipt missing')
        raw=path.read_bytes();receipt=json.loads(raw);observation=receipt.get('provider_observation',{})
        if (receipt.get('result')!='verified' or receipt.get('service')!=service or receipt.get('feature_id')!=feature or
            receipt.get('feature_tag')!=tag or receipt.get('hostname')!=hosts[service] or receipt.get('candidate_sha256')!=candidate or
            observation.get('cmdb_sha256')!=cmdb or observation.get('node')!='dev-k3s-v5' or
            observation.get('instance_id')!=instance or observation.get('ip')!=receipt.get('address') or
            receipt.get('action') not in ('create','update','noop') or not receipt.get('record_id')):
            raise ValueError('DNS receipt differs from verified candidate or target')
        result[service]={'hostname':hosts[service],'record_id':receipt['record_id'],'action':receipt['action'],
                         'address':receipt['address'],'receipt_sha256':hashlib.sha256(raw).hexdigest()}
    if len({row['address'] for row in result.values()})!=1: raise ValueError('DNS services disagree on target')
    return {'schema':'feature-sit-dns-evidence/v1','feature_id':feature,'feature_tag':tag,'candidate_sha256':candidate,
            'cmdb_sha256':cmdb,'instance_id':instance,'services':result,'tls_acceptance':'NOT_RUN','business_acceptance':'NOT_RUN'}

if __name__=='__main__':
    try:
        e=os.environ; hosts={service:e[service.upper()+'_HOST'] for service in ('console','accounts','billing')}
        evidence=verify(Path(e['DNS_EVIDENCE_ROOT']),e['FEATURE_ID'],e['FEATURE_TAG'],e['CANDIDATE_SHA256'],e['CMDB_SHA256'],e['INSTANCE_ID'],hosts)
        print(json.dumps(evidence,sort_keys=True))
    except Exception:
        print('::error::Same-run DNS receipts incomplete or inconsistent',file=sys.stderr);sys.exit(1)
