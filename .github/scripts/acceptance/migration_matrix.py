#!/usr/bin/env python3
"""Control-plane-only migration artifact identity, bounded download and matrix plan."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import select
import time
import zipfile


def api(path, binary=False, token=None):
    # Authenticated gh handles GitHub's signed archive redirect. Never consume a
    # caller URL or archive_download_url, and never buffer unbounded stdout.
    if not isinstance(path,str) or not path.startswith('repos/') or any(part in ('.','..') for part in path.split('/')) or '://' in path:
        raise ValueError('invalid GitHub API path')
    limit=2_000_000 if binary else 4_000_000
    env = None if token is None else dict(os.environ, GH_TOKEN=token)
    process=subprocess.Popen(['gh','api','--hostname','github.com',path],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env)
    output=bytearray();deadline=time.monotonic()+120
    try:
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ValueError('GitHub retrieval timeout')
            ready,_,_=select.select([process.stdout],[],[],min(remaining,1))
            if not ready:continue
            chunk=os.read(process.stdout.fileno(),min(65_536,limit-len(output)+1))
            if not chunk:break
            output.extend(chunk)
            if len(output)>limit:raise ValueError('GitHub response exceeds size limit')
        if process.wait(timeout=max(.01,deadline-time.monotonic()))!=0:raise ValueError('GitHub retrieval failed')
        return bytes(output) if binary else json.loads(output)
    finally:
        if process.poll() is None:process.kill();process.wait()
        process.stdout.close()


def artifact_file(repo, artifact_id, run_id, attempt, name, filename, head_sha):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):raise ValueError('invalid repository')
    if any(type(x) is bool or not re.fullmatch('[1-9][0-9]*',str(x)) for x in (artifact_id,run_id,attempt)):raise ValueError('invalid artifact/run identity')
    meta=api(f'repos/{repo}/actions/artifacts/{artifact_id}')
    run=api(f'repos/{repo}/actions/runs/{run_id}')
    if (str(meta.get('id'))!=str(artifact_id) or meta.get('expired') is not False or meta.get('name')!=name or
        type(meta.get('size_in_bytes')) is not int or not 0<meta['size_in_bytes']<=2_000_000 or
        str(meta.get('workflow_run',{}).get('id'))!=str(run_id) or
        str(run.get('run_attempt'))!=str(attempt) or run.get('head_sha')!=head_sha or
        run.get('repository',{}).get('full_name')!=repo or
        run.get('status')!='completed' or run.get('conclusion')!='success'):
        raise ValueError('artifact provenance mismatch')
    archive=api(f'repos/{repo}/actions/artifacts/{artifact_id}/zip',binary=True)
    if len(archive)>2_000_000:raise ValueError('oversized artifact archive')
    if meta.get('digest')!='sha256:'+hashlib.sha256(archive).hexdigest():raise ValueError('archive digest mismatch')
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        entries=zipped.infolist()
        if len(entries)>100 or sum(x.file_size for x in entries)>4_000_000:raise ValueError('oversized artifact content')
        for item in entries:
            path=Path(item.filename)
            mode=(item.external_attr>>16)&0o170000
            if (path.is_absolute() or '..' in path.parts or '\\' in item.filename or
                mode==0o120000 or item.flag_bits&1):raise ValueError('unsafe artifact entry')
        matches=[x for x in entries if x.filename==filename]
        if len(matches)!=1 or matches[0].file_size>2_000_000:raise ValueError('invalid artifact file')
        return zipped.read(matches[0])


def validate_data_plan(config, environment, toolkit_sha):
    plan=config.get('post_migration_v5')
    if plan is None:return []
    if not isinstance(plan,dict) or plan.get('schema_version')!='v5-post-migration/v1':raise ValueError('invalid plan')
    if plan.get('environment')!=environment or plan.get('toolkit_sha')!=toolkit_sha:raise ValueError('wrong caller/environment')
    for key in ('toolkit_sha','gitops_sha','iac_sha','playbooks_sha','infra_head_sha'):
        if not isinstance(plan.get(key),str) or not re.fullmatch('[a-f0-9]{40}',plan[key]):raise ValueError('immutable SHA required')
    if plan.get('required_checks')!=[f'V5-{n:02}' for n in range(1,24)]:raise ValueError('23 checks required')
    for key in ('cmdb_artifact_id','infra_run_id','infra_run_attempt'):
        if not re.fullmatch('[1-9][0-9]*',str(plan.get(key,''))):raise ValueError('invalid infrastructure provenance')
    if not re.fullmatch(r'https://[a-zA-Z0-9.-]+(?::[0-9]+)?',plan.get('vault_addr','')):raise ValueError('explicit TLS Vault endpoint required')
    targets=plan.get('targets')
    if not isinstance(targets,list) or not targets or len(targets)>20:raise ValueError('target coverage required')
    if len({t['host'] for t in targets})!=len(targets):raise ValueError('duplicate target')
    rows=[]
    for t in targets:
        if not re.fullmatch('[A-Za-z0-9_.-]+',t['host']) or not re.fullmatch('[1-9][0-9]*',t['host_id']):raise ValueError('invalid host')
        if not re.fullmatch('[a-f0-9]{32}',t['machine_id']) or not t['known_hosts'].strip():raise ValueError('trusted machine/key required')
        for key in ('namespace','database_pod','database_user','database_name','source_name','source_namespace'):
            if not re.fullmatch('[A-Za-z0-9_.-]+',t[key]):raise ValueError('invalid service selector')
        if not re.fullmatch('[0-9]+',t['schema']) or type(t['expected_agents']) is not int or t['expected_agents']<1:raise ValueError('invalid assertions')
        rows.append({'host':t['host'],'playbooks_sha':plan['playbooks_sha'],'vault_addr':plan['vault_addr'],
                     'plan':{'schema_version':'v5-owner-plan/v1','environment':environment,'playbooks_sha':plan['playbooks_sha'],
                             'gitops_sha':plan['gitops_sha'],'target':t},
                     'iac_sha':plan['iac_sha'],
                     **{k:plan[k] for k in ('cmdb_artifact_id','cmdb_artifact_name','infra_run_id','infra_run_attempt','infra_head_sha')}})
    return rows


def main():
    try:
        repo=os.environ['GITHUB_REPOSITORY'];sha=os.environ['GITHUB_SHA']
        mode=os.environ['V5_MODE']
        if mode=='materialize':
            row=json.loads(os.environ['V5_MATRIX_ROW']);directory=Path(os.environ['RUNNER_TEMP'])/'v5-input';directory.mkdir(mode=0o700)
            raw=artifact_file(repo,row['cmdb_artifact_id'],row['infra_run_id'],row['infra_run_attempt'],row['cmdb_artifact_name'],'cmdb.json',row['infra_head_sha'])
            cmdb=json.loads(raw)
            provenance=cmdb.get('source_shas',{})
            if provenance.get('iac_sha')!=row['iac_sha'] or provenance.get('gitops_sha')!=row['plan']['gitops_sha']:
                raise ValueError('CMDB producer source SHAs do not match the reviewed plan')
            plan=row['plan'];plan['run_id']=f"v5-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}-{row['host']}"
            (directory/'cmdb.json').write_bytes(raw);(directory/'plan.json').write_text(json.dumps(plan))
        else:raise ValueError('unknown mode')
    except (OSError,KeyError,ValueError,TypeError,subprocess.SubprocessError,zipfile.BadZipFile):
        raise SystemExit('V5 matrix blocked: missing or mismatched migration plan, provenance, target or immutable source.')


if __name__=='__main__':main()
