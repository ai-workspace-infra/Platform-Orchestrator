"""Reusable verification of immutable workflow and artifact provenance."""
import hashlib
import re


def verify_artifact(api, artifact_file, spec):
    """Return a verified artifact member from the declared successful run."""
    required = {'repository','run_id','attempt','workflow','event','ref','commit','artifact_id',
                'artifact_name','artifact_digest','filename','file_sha256'}
    if set(spec) != required:
        raise ValueError('incomplete artifact provenance contract')
    repo=spec['repository']
    if not isinstance(repo,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
        raise ValueError('invalid repository')
    if any(type(spec[k]) is not int or spec[k] <= 0 for k in ('run_id','attempt','artifact_id')):
        raise ValueError('invalid run or artifact identifier')
    if not re.fullmatch(r'[0-9a-f]{40}',spec['commit']) or not re.fullmatch(r'[0-9a-f]{64}',spec['file_sha256']):
        raise ValueError('immutable commit and digest required')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',spec['artifact_digest']):
        raise ValueError('invalid archive digest')
    run=api(f"repos/{repo}/actions/runs/{spec['run_id']}")
    artifact=api(f"repos/{repo}/actions/artifacts/{spec['artifact_id']}")
    if (run.get('id')!=spec['run_id'] or run.get('run_attempt')!=spec['attempt']
        or run.get('repository',{}).get('full_name')!=repo or run.get('event')!=spec['event']
        or run.get('path')!=spec['workflow'] or run.get('head_branch')!=spec['ref']
        or run.get('head_sha')!=spec['commit'] or run.get('status')!='completed' or run.get('conclusion')!='success'):
        raise ValueError('run provenance mismatch')
    if (artifact.get('id')!=spec['artifact_id'] or artifact.get('name')!=spec['artifact_name']
        or artifact.get('digest')!=spec['artifact_digest'] or artifact.get('expired') is not False
        or artifact.get('workflow_run',{}).get('id')!=spec['run_id']
        or artifact.get('workflow_run',{}).get('head_sha')!=spec['commit']):
        raise ValueError('artifact provenance mismatch')
    raw=artifact_file(repo,spec['artifact_id'],spec['run_id'],spec['attempt'],spec['artifact_name'],spec['filename'],spec['commit'])
    if hashlib.sha256(raw).hexdigest()!=spec['file_sha256']:
        raise ValueError('artifact member digest mismatch')
    return raw
