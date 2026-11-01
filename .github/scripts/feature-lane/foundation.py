#!/usr/bin/env python3
"""Authenticate historical SIT foundation evidence for the generic feature lane."""
import base64
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import yaml

REPO = 'ai-workspace-infra/platform-ops-toolkit'
GITOPS = 'ai-workspace-infra/gitops'
SHA = re.compile(r'[0-9a-f]{40}')

def require(ok,message):
 if not ok:raise ValueError(message)

def positive(value):
 require(type(value) is not bool and re.fullmatch('[1-9][0-9]*',str(value)),'positive numeric locator required');return int(value)

def pages(reader,path,key=None):
 result=[]
 for page in range(1,21):
  data=reader.api(path+('&' if '?' in path else '?')+f'per_page=100&page={page}')
  rows=data[key] if key else data
  require(isinstance(rows,list),'malformed GitHub page');result.extend(rows)
  if len(rows)<100:return result
 raise ValueError('bounded GitHub pagination exceeded')

def run_identity(raw,repo,sha,workflow,event='push'):
 require(raw.get('repository',{}).get('full_name')==repo and raw.get('head_repository',{}).get('full_name')==repo,'fork/foreign run rejected')
 require(raw.get('head_sha')==sha and raw.get('path','').split('@')[0]==workflow and raw.get('event')==event,'build source/workflow mismatch')
 require(raw.get('status')=='completed' and raw.get('conclusion')=='success','producer not successful')

def read_workflow(reader,repo,path,sha):
 require(isinstance(sha,str) and SHA.fullmatch(sha),'workflow source must be immutable')
 data=reader.api(f'repos/{repo}/contents/{path}?ref={sha}')
 require(data.get('path')==path and data.get('type')=='file' and data.get('encoding')=='base64' and 0<data.get('size',0)<100000,'workflow source unavailable')
 return yaml.safe_load(base64.b64decode(data['content']))

def foundation_dependencies(reader,source,repo=REPO):
 workflow=read_workflow(reader,repo,'.github/workflows/dev-host-lifecycle.yml',source)
 iac=workflow.get('jobs',{}).get('iac',{}).get('with',{}).get('iac_ref','')
 require(isinstance(iac,str) and SHA.fullmatch(iac),'foundation IaC ref must be immutable')
 use=workflow.get('jobs',{}).get('bootstrap',{}).get('uses','')
 prefix='ai-workspace-infra/playbooks/.github/workflows/dev-k3s-bootstrap.yml@'
 require(use.startswith(prefix) and SHA.fullmatch(use[len(prefix):]),'foundation bootstrap ref must be immutable')
 boot=read_workflow(reader,'ai-workspace-infra/playbooks','.github/workflows/dev-k3s-bootstrap.yml',use[len(prefix):])
 refs=[]
 for job in boot.get('jobs',{}).values():
  for step in job.get('steps',[]):
   conf=step.get('with',{})
   if str(step.get('uses','')).startswith('actions/checkout@') and conf.get('repository')=='ai-workspace-infra/playbooks':refs.append(conf.get('ref',''))
 require(len(refs)==1 and isinstance(refs[0],str) and SHA.fullmatch(refs[0]),'bootstrap implementation ref must be immutable')
 return iac,refs[0]

def canonical_toolkit_repository(reader):
 metadata=reader.api(f'repos/{REPO}')
 require(metadata.get('id')==1284966060 and metadata.get('full_name') in (REPO,'ai-workspace-infra/Platform-Orchestrator'),'unexpected foundation repository identity')
 return metadata['full_name']

def load(name, path):
 spec=importlib.util.spec_from_file_location(name,path)
 module=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(module)
 return module

def select_runtime_inventory(summary,inventories,matrix):
 require(summary.get('result')=='applied_verified','runtime handoff requires applied_verified')
 context=summary['context']
 require(context.get('action')=='apply' and context.get('stages')==['resources'],'runtime handoff requires a resources-only apply')
 targets=context.get('targets',[])
 require(len(targets)==1 and isinstance(targets[0].get('id'),str),'runtime handoff requires exactly one declared target')
 target=targets[0];target_id=target['id']
 require(target.get('environment')==context.get('environment'),'target/environment identity mismatch')
 require(all(isinstance(target.get(key),str) and target[key] for key in ('project','provider','account','namespace')),'target identity is incomplete')
 state_key=target.get('stages',{}).get('resources',{}).get('state',{}).get('key')
 require(isinstance(state_key,str) and state_key,'target resources state identity is missing')
 require(set(inventories)=={target_id},'unexpected inventory target')
 cmdb=inventories[target_id]
 require(isinstance(cmdb,dict) and len(cmdb)==1,'runtime CMDB must contain exactly one host')
 host,facts=next(iter(cmdb.items()))
 require(isinstance(host,str) and isinstance(facts,dict),'runtime host facts are malformed')
 require(facts.get('name')==host and facts.get('label')==host,'runtime host identity mismatch')
 require(str(facts.get('instance_id','')).isdecimal() and int(facts['instance_id'])>0 and facts.get('ip'),'missing runtime instance identity')
 require(summary.get('deploy_matrix')==matrix==[{'target_id':target_id,'host':host,**facts}],'deploy matrix does not match verified runtime inventory')
 receipts=summary.get('receipts',[])
 require(len(receipts)==1 and receipts[0].get('target_id')==target_id and receipts[0].get('stage')=='resources','missing resource receipt')
 raw=json.dumps(cmdb,sort_keys=True,indent=2)+'\n'
 require(hashlib.sha256(raw.encode()).hexdigest()==receipts[0].get('inventory_sha256'),'selected inventory digest differs from owner receipt')
 return raw,str(facts['instance_id'])

def foundation(reader,run_id,summary_id,bootstrap_id):
 run_id=positive(run_id);summary_id=positive(summary_id);bootstrap_id=positive(bootstrap_id)
 # GitHub reports the canonical repository name after a rename. Authenticate
 # the original fixed repository ID before using its canonical API identity.
 repo=canonical_toolkit_repository(reader)
 run=reader.api(f'repos/{repo}/actions/runs/{run_id}')
 source=run.get('head_sha','')
 require(isinstance(source,str) and SHA.fullmatch(source),'foundation workflow commit missing')
 run_identity(run,repo,source,'.github/workflows/dev-host-lifecycle.yml','workflow_dispatch')
 main=reader.api(f'repos/{repo}/git/ref/heads/main')['object']['sha']
 require(reader.api(f'repos/{repo}/compare/{source}...{main}').get('status') in ('ahead','identical'),'foundation caller is not on protected main')
 iac,playbooks=foundation_dependencies(reader,source,repo)
 require(run.get('head_branch')=='main' and run.get('run_attempt')==2,'reviewed bootstrap run attempt2 required')
 historical=reader.api(f'repos/{repo}/actions/runs/{run_id}/attempts/1')
 require(historical.get('head_sha')==source and historical.get('run_attempt')==1,'historical source attempt missing')
 jobs=pages(reader,f'repos/{repo}/actions/runs/{run_id}/attempts/1/jobs','jobs')
 require(any(j.get('name')=='iac / summary' and j.get('conclusion')=='success' for j in jobs),'original summary job not successful')
 require(any(j.get('name','').startswith('iac / resources (dev-akamai-dev-k3s-v5,') and j.get('name','').endswith(' / resources') and j.get('conclusion')=='success' for j in jobs),'original resource job not successful')
 bootstrap_jobs=pages(reader,f'repos/{repo}/actions/runs/{run_id}/attempts/2/jobs','jobs')
 require(any(j.get('name')=='bootstrap / bootstrap' and j.get('conclusion')=='success' for j in bootstrap_jobs),'bootstrap attempt2 not successful')
 # Download authentication uses current successful aggregate run attempt2. The
 # immutable artifact name/document and historical jobs prove IaC source attempt1.
 def payload(aid,name,filename):return json.loads(reader.artifact_file(repo,aid,run_id,2,name,filename,source))
 summary=payload(summary_id,f'iac-summary-{run_id}-1','summary.json')
 inventories=payload(summary_id,f'iac-summary-{run_id}-1','inventory.json')
 context=summary.get('context',{})
 platform=context.get('gitops_sha','')
 require(isinstance(platform,str) and SHA.fullmatch(platform),'full platform commit required')
 main=reader.api(f'repos/{GITOPS}/git/ref/heads/main')['object']['sha']
 require(reader.api(f'repos/{GITOPS}/compare/{platform}...{main}').get('status') in ('ahead','identical'),'platform commit is not on protected main')
 require(context.get('run_id')==str(run_id) and context.get('run_attempt')=='1' and context.get('workflow_sha')==source and context.get('gitops_sha')==platform and context.get('iac_sha')==iac and context.get('workflow_ref')=='ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-host-lifecycle.yml@refs/heads/main','original owner document provenance mismatch')
 require(all(r.get('run_attempt')=='1' and r.get('run_id')==str(run_id) and r.get('workflow_sha')==source and r.get('iac_sha')==iac and r.get('result')=='applied_verified' for r in summary.get('receipts',[])),'resource receipt identity mismatch')
 raw,instance=select_runtime_inventory(summary,inventories,summary['deploy_matrix'])
 bootstrap=payload(bootstrap_id,f'dev-k3s-bootstrap-{run_id}-2','receipt.json')
 digest=hashlib.sha256(raw.encode()).hexdigest()
 require(bootstrap.get('schema_version')==1 and bootstrap.get('result')=='PASS' and bootstrap.get('environment')=='dev' and bootstrap.get('instance_id')==instance and bootstrap.get('run_id')==str(run_id) and bootstrap.get('cmdb_sha256')==digest and bootstrap.get('playbooks_sha')==playbooks,'bootstrap receipt binding mismatch')
 require(all(bootstrap.get(k) is True for k in ('node_ready','source_ready','root_ready')) and bootstrap.get('node')=='dev-k3s-v5' and bootstrap.get('hostname')=='dev-k3s-v5','bootstrap target not Ready')
 require(bootstrap.get('gitops_sha')==platform and bootstrap.get('source_revision')=='sha1:'+platform and bootstrap.get('applied_revision')=='sha1:'+platform,'bootstrap protected platform mismatch')
 require(bootstrap.get('node_info',{}).get('kubeletVersion')=='v1.37.1+k3s1' and bootstrap.get('node_info',{}).get('architecture')=='amd64','bootstrap runtime mismatch')
 for k in ('node_uid','cluster_uid'):require(re.fullmatch('[0-9a-f-]{36}',bootstrap.get(k,'')),'bootstrap UID missing')
 return raw,dict(instance_id=instance,cmdb_sha256=digest,node_uid=bootstrap['node_uid'],cluster_uid=bootstrap['cluster_uid'],platform_sha=platform,iac_sha=iac,bootstrap_playbooks_sha=playbooks,source_run=run_id,iac_source_attempt=1,bootstrap_source_attempt=2,summary_artifact=summary_id,bootstrap_artifact=bootstrap_id)
