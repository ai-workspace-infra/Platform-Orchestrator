#!/usr/bin/env python3
"""Actual CI integration identity qualification. No authorization/deployment receipt."""
import importlib.util,json,os,re,subprocess
from pathlib import Path

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def main():
 def require(ok,message):
  if not ok:raise ValueError(message)
 require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GH_TOKEN'),'actual CI integration token required; no local credential fallback')
 module=load('dev_resolve',Path(__file__).with_name('resolve.py'))
 reader=load('qualified_shared_reader',Path(os.environ['EVIDENCE_ROOT'])/'.github/scripts/acceptance/migration_matrix.py')
 original=reader.api;observed=[];denied=[]
 def authenticated(path,binary=False):
  try:
   result=original(path,binary);observed.append({'api':path,'result':'read_success'});return result
  except Exception:
   # Same integration identity; headers only, never a user credential fallback.
   # Capture locally and emit only the numeric HTTP status, never Location/body.
   p=subprocess.run(['gh','api','--hostname','github.com','--include','--silent',path],capture_output=True,text=True,timeout=30)
   statuses=re.findall(r'(?m)^HTTP/[^ ]+ ([0-9]{3})',p.stdout)
   status=int(statuses[-1]) if statuses else 'UNKNOWN'
   observed.append({'api':path,'status':status,'result':'request_failed'})
   if status in (401,403):denied.append({'api':path,'status':status})
   raise ValueError('CI API access failed: '+path+' HTTP '+str(status)) from None
 reader.api=authenticated
 # Do not synthesize source.workflow_ref=main; this PR job only proves API access.
 pr=reader.api('repos/ai-workspace-infra/gitops/pulls/605')
 head=pr.get('head',{}).get('sha');require(re.fullmatch('[0-9a-f]{40}',head or ''),'GitOps PR identity unavailable')
 checks=module.pages(reader,f'repos/ai-workspace-infra/gitops/commits/{head}/check-runs','check_runs')
 require(isinstance(checks,list),'GitOps checks API unavailable')
 _,identity=module.foundation(reader,40353330431,12664517641,12668512699)
 rows=[('accounts','ai-workspace-services/accounts',40222728214,'8d1b09a6f2022af221b2a817d516952af41ced0e','ghcr.io/ai-workspace-services/accounts@sha256:6edd156ce6974dfd0cd7486beebbb446091e4019eacf3c272e05aba4a609737d'),('console','ai-workspace-services/portal',40256113380,'2a272f295235efdd39f469245ad74177d1a5ff5d','ghcr.io/ai-workspace-services/console@sha256:03ffaf0174c64aede7602b5d566ff27921f760e134028afabb62b646324228f9'),('caddy','ai-workspace-infra/artifacts',30419099530,'959d6c8ec8dfdf1224fe3b976ae4548d38947332','ghcr.io/ai-workspace-infra/caddy-cloudflare@sha256:9895385033fea2bdb445841b45f37e6cd58b9e071a16e4c147e483abb74a0acf')]
 rows.append(('accounts','ai-workspace-services/accounts',40378515318,'450ab9940071883139d4a73e6cfd2f4b77d193ba','ghcr.io/ai-workspace-services/accounts@sha256:97a58ebe7fab56432777591604491c2dea7fc7cc57cd35820fedef78fa328572'))
 proofs=[]
 for component,repo,rid,sha,image in rows:
  run=reader.api(f'repos/{repo}/actions/runs/{rid}');module.run_identity(run,repo,sha,module.COMPONENTS[component][2],'workflow_dispatch' if rid==40378515318 else 'push')
  module.source_gate(reader,repo,sha,module.COMPONENTS[component][2],'sit',run)
  proof=module.publisher_proof(reader,component,repo,rid,sha,image,rid==40378515318)
  proofs.append({'component':component,'preview_dispatch':rid==40378515318,'job_id':proof['job_id'],'source_sha':sha,'image':image,'log_sha256':proof['log_sha256'],'matched_checkout_and_push':True,'preview_flags':proof.get('preview_flags')})
 reader.api('repos/ai-workspace-services/accounts/commits/450ab9940071883139d4a73e6cfd2f4b77d193ba/pulls?per_page=100')
 reader.api('repos/ai-workspace-services/accounts/contents/.github/workflows/ci-pipeline.yml?ref=450ab9940071883139d4a73e6cfd2f4b77d193ba')
 require(not denied,'integration token denied cross-repository API: '+json.dumps(denied,sort_keys=True))
 print(json.dumps({'kind':'ci-integration-readonly-qualification','result':'api_access_verified','deployment':'NOT_RUN','authorization_receipt':False,'run_id':os.environ.get('GITHUB_RUN_ID'),'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'gitops_head_sample':head,'checks_read':len(checks),'foundation_cmdb_sha256':identity['cmdb_sha256'],'publisher_matches':proofs,'api_observations':observed},sort_keys=True))
if __name__=='__main__':
 try:main()
 except Exception as error:raise SystemExit('CI readonly identity qualification failed: '+(str(error) if type(error) is ValueError else type(error).__name__)) from None
