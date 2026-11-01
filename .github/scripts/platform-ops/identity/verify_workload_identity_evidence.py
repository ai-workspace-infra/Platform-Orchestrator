#!/usr/bin/env python3
"""Resolve and verify IaC/bootstrap receipts from one protected Selfhost run."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import resolve_workload_identity as resolver

ROOT=Path(__file__).resolve().parents[4]

def _module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

provenance=_module('workflow_artifact_provenance','.github/scripts/platform-ops/evidence/workflow_artifact_provenance.py')
matrix=_module('migration_matrix','.github/scripts/acceptance/migration_matrix.py')


def _one(items, predicate, message):
    matches=[item for item in items if predicate(item)]
    if len(matches)!=1:
        raise ValueError(message)
    return matches[0]


def _find_child_run(repo, prefix, workflow_path, api):
    for page in range(1,11):
        response=api(f'repos/{repo}/actions/runs?event=workflow_dispatch&per_page=100&page={page}')
        rows=response.get('workflow_runs')
        if not isinstance(rows,list):
            raise ValueError('invalid workflow run listing')
        matches=[row for row in rows if row.get('display_title','').startswith(prefix)
                 and row.get('path')==workflow_path and row.get('event')=='workflow_dispatch'
                 and row.get('head_branch')=='main' and row.get('status')=='completed']
        if len(matches)>1:
            raise ValueError('correlated workflow child is ambiguous')
        if matches:
            return matches[0]
        if len(rows)<100:
            break
    raise ValueError('correlated workflow child is missing')


def _artifacts(repo, run_id, api):
    response=api(f'repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100')
    rows=response.get('artifacts')
    if not isinstance(rows,list):
        raise ValueError('invalid artifact listing')
    return rows


def _download(repo, run, artifact, filename, api, artifact_file, allowed_conclusions):
    if (not isinstance(artifact,dict) or artifact.get('expired') is not False
            or not isinstance(artifact.get('digest'),str)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}',artifact['digest'])):
        raise ValueError('invalid or expired workflow artifact')
    row={
        'repository':repo,'run_id':run['id'],'attempt':run['run_attempt'],
        'workflow':run['path'],'event':run['event'],'ref':run['head_branch'],
        'commit':run['head_sha'],'artifact_id':artifact['id'],'artifact_name':artifact['name'],
        'artifact_digest':artifact['digest'],'filename':filename,'file_sha256':'0'*64,
    }
    raw=artifact_file(repo,row['artifact_id'],row['run_id'],row['attempt'],row['artifact_name'],
                      filename,row['commit'],allowed_conclusions=allowed_conclusions)
    row['file_sha256']=hashlib.sha256(raw).hexdigest()
    return raw,row


def resolve_current_run(spec, parent_run_id, repository, api=matrix.api, artifact_file=matrix.artifact_file):
    """Materialize ephemeral artifact provenance from a completed protected parent run."""
    if not re.fullmatch(r'[1-9][0-9]*',str(parent_run_id)):
        raise ValueError('valid parent run ID required')
    evidence=spec['evidence']
    if evidence.get('source')!='current-run':
        raise ValueError('GitOps declaration must select current-run evidence')
    parent=api(f'repos/{repository}/actions/runs/{parent_run_id}')
    if (parent.get('id')!=int(parent_run_id) or parent.get('repository',{}).get('full_name')!=repository
            or parent.get('event')!='workflow_dispatch' or parent.get('path')!=evidence.get('workflow')
            or parent.get('head_branch')!='main' or parent.get('status')!='completed'):
        raise ValueError('parent run provenance mismatch')
    attempt=parent.get('run_attempt')
    if type(attempt) is not int or attempt<1:
        raise ValueError('invalid parent run attempt')
    parent_artifacts=_artifacts(repository,parent_run_id,api)
    request_artifact=_one(parent_artifacts,lambda row:row.get('name')==f'selfhost-parent-request-{attempt}',
                          'parent request artifact missing or ambiguous')
    request_raw,_=_download(repository,parent,request_artifact,'selfhost-parent-request.json',api,artifact_file,
                            ('success','failure'))
    request=json.loads(request_raw)
    if (request.get('operation')!='deploy' or request.get('__parent_event_name')!='workflow_dispatch'
            or request.get('__parent_ref_name')!='main' or request.get('__parent_head_sha')!=parent.get('head_sha')):
        raise ValueError('parent request is not an authorized deployment')
    infra_artifact=_one(parent_artifacts,lambda row:row.get('name')==f'selfhost-parent-stage-infra-{attempt}',
                        'successful infrastructure-stage receipt missing or ambiguous')
    infra_raw,_=_download(repository,parent,infra_artifact,'selfhost-stage-result.json',api,artifact_file,
                          ('success','failure'))
    infra_result=json.loads(infra_raw)
    if (infra_result.get('schema')!=1 or infra_result.get('stage')!='infra'
            or infra_result.get('context',{}).get('result')!='success'):
        raise ValueError('infrastructure stage did not succeed')
    infra_stage_id=int(infra_result['run_id']);infra_attempt=int(infra_result['run_attempt'])
    infra_stage=api(f'repos/{repository}/actions/runs/{infra_stage_id}')
    if (infra_stage.get('event')!='workflow_dispatch' or infra_stage.get('path')!='.github/workflows/selfhost-stage-infra.yml'
            or infra_stage.get('head_branch')!='main' or infra_stage.get('status')!='completed'
            or infra_stage.get('conclusion')!='success' or infra_stage.get('run_attempt')!=infra_attempt):
        raise ValueError('infrastructure stage provenance mismatch')
    iac_run=_find_child_run(repository,f'iac:{infra_stage_id}:{infra_attempt}:',
                            '.github/workflows/iac-orchestrator.yml',api)
    deploy_run=_find_child_run(repository,f'Selfhost Stage deploy-{parent_run_id}-{attempt}',
                               '.github/workflows/selfhost-stage-deploy-container.yml',api)
    if str(iac_run.get('conclusion'))!='success':
        raise ValueError('IaC child did not succeed')
    iac_run=api(f"repos/{repository}/actions/runs/{iac_run['id']}")
    deploy_run=api(f"repos/{repository}/actions/runs/{deploy_run['id']}")
    iac_attempt=iac_run.get('run_attempt');deploy_attempt=deploy_run.get('run_attempt')
    target=spec['target'];node=target['node']
    iac_artifacts=_artifacts(repository,iac_run['id'],api)
    iac_artifact=_one(iac_artifacts,lambda row:row.get('name')==f"iac-summary-{iac_run['id']}-{iac_attempt}",
                      'IaC summary artifact missing or ambiguous')
    summary_raw,iac_row=_download(repository,iac_run,iac_artifact,'summary.json',api,artifact_file,('success',))
    inventory_raw,_=_download(repository,iac_run,iac_artifact,'inventory.json',api,artifact_file,('success',))
    deploy_artifacts=_artifacts(repository,deploy_run['id'],api)
    bootstrap_artifact=_one(deploy_artifacts,lambda row:row.get('name','').startswith(f'k3s-bootstrap-{node}-'),
                            'K3s bootstrap artifact missing or ambiguous')
    bootstrap_raw,bootstrap_row=_download(repository,deploy_run,bootstrap_artifact,
                                            f'k3s-bootstrap-{node}.json',api,artifact_file,('success','failure'))
    bootstrap=json.loads(bootstrap_raw);summary=json.loads(summary_raw);context=summary['context']
    if (context.get('action')!='apply' or context.get('environment')!=spec['environment']
            or context.get('gitops_sha')!=infra_result.get('context',{}).get('outputs',{}).get('gitops_sha')
            or context.get('correlation_id','').split(':',1)[0]!=str(infra_stage_id)
            or context.get('correlation_id','').split(':',2)[1:2]!=[str(infra_attempt)]):
        raise ValueError('IaC summary does not belong to the parent infrastructure stage')
    if (target['iacTargetManifest'] not in context.get('declaration_files',{})
            or not any(t.get('stages',{}).get('resources',{}).get('manifest')==target['declaration']
                       for t in context.get('targets',[]))):
        raise ValueError('IaC target manifest differs from identity declaration')
    evidence_spec=copy.deepcopy(spec)
    evidence_spec['evidence']={
        'bootstrap':{**bootstrap_row,'gitopsSha':bootstrap.get('gitops_sha')},
        'iac':{**iac_row,'iacSha':context.get('iac_sha'),'inventorySha256':hashlib.sha256(inventory_raw).hexdigest()},
    }
    return evidence_spec


def artifact_contract(row, filename=None):
    result={'repository':row['repository'],'run_id':row['run_id'],'attempt':row['attempt'],
            'workflow':row['workflow'],'event':row['event'],'ref':row['ref'],'commit':row['commit'],
            'artifact_id':row['artifact_id'],'artifact_name':row['artifact_name'],
            'artifact_digest':row['artifact_digest'],'filename':row['filename'],'file_sha256':row['file_sha256']}
    if filename:
        result['filename']=filename
    return result


def verify(spec, parent_run_id=None, repository=None, api=matrix.api, artifact_file=matrix.artifact_file):
    if spec.get('evidence',{}).get('source')=='current-run':
        if not repository:
            raise ValueError('workflow repository required for current-run evidence')
        spec=resolve_current_run(spec,parent_run_id,repository,api,artifact_file)
    e=spec['evidence'];target=spec['target'];boot=e['bootstrap'];iac=e['iac']
    if boot.get('ref')!='main' or iac.get('ref')!='main':
        raise ValueError('base workflow repositories must resolve from main')
    raw_boot=provenance.verify_artifact(api,artifact_file,artifact_contract(boot),
                                        allowed_conclusions=('success','failure'))
    raw_iac=provenance.verify_artifact(api,artifact_file,artifact_contract(iac))
    inventory=provenance.verify_artifact(api,artifact_file,{**artifact_contract(iac),
                                                             'filename':'inventory.json',
                                                             'file_sha256':iac['inventorySha256']})
    try:
        b=json.loads(raw_boot);summary=json.loads(raw_iac);c=summary['context']
        if (b['result']!='FLUX_HANDOVER_VERIFIED' or b['node']!=target['node']
                or b['version']!=target['kubernetesVersion'] or b['gitops_sha']!=boot['gitopsSha']
                or b['common']['result']!='COMMON_NODE_VERIFIED' or b['common']['node']!=target['node']
                or b['common']['os_identities']!='OS_IDENTITY_CHECKS_PASSED'):
            raise ValueError('bootstrap receipt does not satisfy identity prerequisites')
        if (summary['result']!='applied_verified' or c['action']!='apply' or c['environment']!=spec['environment']
                or c['gitops_sha']!=boot['gitopsSha'] or c['iac_sha']!=iac['iacSha']
                or str(c['run_id'])!=str(iac['run_id']) or str(c['run_attempt'])!=str(iac['attempt'])
                or target['iacTargetManifest'] not in c['declaration_files']):
            raise ValueError('IaC summary does not match target and bootstrap')
        matches=[t for t in c['targets'] if t['environment']==spec['environment'] and t['provider']==target['provider'] and t['account']==target['account'] and t['stages']['resources']['manifest']==target['declaration']]
        if len(matches)!=1:
            raise ValueError('IaC selected target does not match identity declaration')
        data=json.loads(inventory)
        matching=[v[target['node']] for v in data.values() if isinstance(v,dict) and target['node'] in v]
        if len(matching)!=1 or str(matching[0]['instance_id'])!=str(b['common']['cmdb_instance_id']):
            raise ValueError('inventory and bootstrap instance differ')
    except (KeyError,TypeError,json.JSONDecodeError):
        raise ValueError('invalid identity evidence') from None
    return {'bootstrap':raw_boot,'summary':raw_iac,'inventory':inventory,
            'bootstrap_sha256':hashlib.sha256(raw_boot).hexdigest(),'summary_sha256':hashlib.sha256(raw_iac).hexdigest(),
            'iac_catalog_manifest':c['manifest_path']}
