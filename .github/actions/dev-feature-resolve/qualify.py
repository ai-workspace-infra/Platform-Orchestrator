#!/usr/bin/env python3
"""Actual CI integration identity qualification. No authorization/deployment receipt."""
import base64,importlib.util,json,os,re,subprocess
import yaml
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
 # Read the explicitly selected candidate and foundation; never emit a deployment receipt.
 pr_number=module.positive(os.environ.get('DEV_SIT_QUALIFY_PR',''))
 pr=reader.api(f'repos/ai-workspace-infra/gitops/pulls/{pr_number}')
 require(pr.get('base',{}).get('ref')=='main' and pr.get('state')=='open','open main-based candidate required')
 head=pr.get('head',{}).get('sha');require(re.fullmatch('[0-9a-f]{40}',head or ''),'GitOps PR identity unavailable')
 checks=module.check_head(reader,head)
 _,identity=module.foundation(reader,os.environ.get('DEV_SIT_FOUNDATION_RUN',''),os.environ.get('DEV_SIT_SUMMARY_ARTIFACT',''),os.environ.get('DEV_SIT_BOOTSTRAP_ARTIFACT',''))
 path='services/distributed-web-saas-fullstack/dev/sit-xconnect-referral/release.yaml'
 content=reader.api(f'repos/ai-workspace-infra/gitops/contents/{path}?ref={head}')
 require(content.get('path')==path and content.get('type')=='file' and content.get('encoding')=='base64','candidate release unavailable')
 release=yaml.safe_load(base64.b64decode(content['content']))
 main=reader.api('repos/ai-workspace-infra/gitops/git/ref/heads/main')['object']['sha']
 require(reader.api(f'repos/ai-workspace-infra/gitops/compare/{main}...{head}').get('status') in ('ahead','identical'),'candidate is not based on current main')
 expected={'schema_version':'dev-feature-candidate/v1','result':'verified','repository':module.GITOPS,'stage':'sit','candidate_pr':pr_number,'candidate_head':head,'base_ref':'main','base_sha':main,'checks':'success','same_repository':True,'main_ancestry_verified':True}
 proofs,provenance=module.prior_candidate_builds(reader,os.environ.get('DEV_SIT_PROVENANCE_RUN',''),os.environ.get('DEV_SIT_PROVENANCE_ARTIFACT',''),expected,release)
 require(not denied,'integration token denied cross-repository API: '+json.dumps(denied,sort_keys=True))
 print(json.dumps({'kind':'ci-integration-readonly-qualification','result':'api_access_verified','deployment':'NOT_RUN','authorization_receipt':False,'run_id':os.environ.get('GITHUB_RUN_ID'),'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'gitops_head_sample':head,'checks_read':len(checks),'foundation_cmdb_sha256':identity['cmdb_sha256'],'publisher_matches':proofs,'prior_provenance':provenance,'api_observations':observed},sort_keys=True))
if __name__=='__main__':
 try:main()
 except Exception as error:raise SystemExit('CI readonly identity qualification failed: '+(str(error) if type(error) is ValueError else type(error).__name__)) from None
