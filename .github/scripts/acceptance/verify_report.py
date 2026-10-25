#!/usr/bin/env python3
"""Verify actual generated report/checksums and exact current matrix identity."""
import hashlib
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def validate(root, row, run_id, attempt):
    root=Path(root)
    names={'report.zh.md','evidence.json','junit.xml'}
    manifest=json.loads((root/'manifest.json').read_text())
    if set(manifest)!=names:raise ValueError('incomplete report files')
    for name in names:
        path=root/name
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:raise ValueError('missing or unsafe evidence')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest[name]:raise ValueError('report digest mismatch')
    data=json.loads((root/'evidence.json').read_text())
    if not isinstance(data,dict):raise ValueError('invalid report object')
    target=row['plan']['target']
    identity={'schema_version':'v5-report/v1','execution_mode':'ssh-playbook-role',
              'environment':row['plan']['environment'],'owner_sha':row['playbooks_sha'],
              'host_id':target['host_id'],'gitops_sha':row['plan']['gitops_sha'],
              'run_id':f"v5-{run_id}-{attempt}-{target['host']}"}
    if any(type(data.get(k)) is not str or data[k]!=v for k,v in identity.items()):raise ValueError('wrong report identity')
    if data.get('scope_verified') is not True or data.get('result')!='PASS':raise ValueError('scope or acceptance not verified')
    checks=data.get('checks')
    if (not isinstance(checks,list) or len(checks)!=23 or not all(isinstance(c,dict) for c in checks) or
        [c.get('id') for c in checks]!=[f'V5-{n:02}' for n in range(1,24)] or
        any(c.get('status')!='PASS' for c in checks)):raise ValueError('missing or non-PASS check')
    suite=ET.parse(root/'junit.xml').getroot()
    if suite.tag!='testsuite' or any(suite.get(k)!=v for k,v in {'tests':'23','failures':'0','errors':'0','skipped':'0'}.items()):raise ValueError('contradictory JUnit summary')
    cases=suite.findall('testcase')
    if ([case.get('name') for case in cases]!=[f'V5-{n:02}' for n in range(1,24)] or
        any(case.find(tag) is not None for case in cases for tag in ('failure','error','skipped'))):raise ValueError('contradictory JUnit checks')
    return True


def main():
    try:validate(os.environ['V5_REPORT_DIR'],json.loads(os.environ['V5_MATRIX_ROW']),os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'])
    except (ValueError,OSError,KeyError,TypeError,ET.ParseError):raise SystemExit('V5 report rejected: missing, mismatched, tampered or incomplete acceptance evidence.')
    print('Exact current matrix report and all 23 required PASS checks verified.')


if __name__=='__main__':main()
