#!/usr/bin/env python3
"""Read-only control plane: authenticated GitHub evidence, never resource execution."""
import io,zipfile,datetime,base64,hashlib,importlib.util,json,os,re
from pathlib import Path
import yaml
REPO='ai-workspace-infra/platform-ops-toolkit'
GITOPS='ai-workspace-infra/gitops'
SOURCE='5542116661b2874a98f3c4fa647f1cdc804f8f76'
IAC='1d3bc5b54a49b946b98e48bf9f73606369b77d02'
PLATFORM='60bf8621c5a0d1dfd3f7ce38758a48740f9f14e7'
PLAYBOOKS='4a5dbb8e1240a096e7818f1da6a925569a3da7ea'
WORKFLOW='ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-feature-deploy.yml@refs/heads/main'
SCOPES={'sit':'sit-xconnect-referral','uat':'uat'}
SHA=re.compile(r'[0-9a-f]{40}')
# Source repository, immutable image repository, reviewed build workflow.
COMPONENTS={
 'caddy':('ai-workspace-infra/artifacts','ai-workspace-infra/caddy-cloudflare','.github/workflows/build-ci-image-caddy.yml'),
 'console':('ai-workspace-services/portal','ai-workspace-services/console','.github/workflows/ci-pipeline.yml'),
 'accounts':('ai-workspace-services/accounts','ai-workspace-services/accounts','.github/workflows/ci-pipeline.yml'),
 'billing':('ai-workspace-services/billing-service','ai-workspace-services/billing-service','.github/workflows/ci-pipeline.yml'),
 'content':('ai-workspace-services/content-service','ai-workspace-services/docs','.github/workflows/ci-pipeline.yml'),
 'postgresql':('ai-workspace-services/postgresql','ai-workspace-services/postgresql','.github/workflows/ci-pipeline.yml')}

def require(ok,message):
 if not ok:raise ValueError(message)

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

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

def foundation(reader,run_id,summary_id,bootstrap_id):
 run_id=positive(run_id);summary_id=positive(summary_id);bootstrap_id=positive(bootstrap_id)
 run=reader.api(f'repos/{REPO}/actions/runs/{run_id}')
 run_identity(run,REPO,SOURCE,'.github/workflows/dev-host-lifecycle.yml','workflow_dispatch')
 require(run.get('head_branch')=='main' and run.get('run_attempt')==2,'reviewed bootstrap run attempt2 required')
 historical=reader.api(f'repos/{REPO}/actions/runs/{run_id}/attempts/1')
 require(historical.get('head_sha')==SOURCE and historical.get('run_attempt')==1,'historical source attempt missing')
 jobs=pages(reader,f'repos/{REPO}/actions/runs/{run_id}/attempts/1/jobs','jobs')
 require(any(j.get('name')=='iac / summary' and j.get('conclusion')=='success' for j in jobs),'original summary job not successful')
 require(any(j.get('name','').startswith('iac / resources (dev-akamai-dev-k3s-v5,') and j.get('name','').endswith(' / resources') and j.get('conclusion')=='success' for j in jobs),'original resource job not successful')
 bootstrap_jobs=pages(reader,f'repos/{REPO}/actions/runs/{run_id}/attempts/2/jobs','jobs')
 require(any(j.get('name')=='bootstrap / bootstrap' and j.get('conclusion')=='success' for j in bootstrap_jobs),'bootstrap attempt2 not successful')
 # Download authentication uses current successful aggregate run attempt2. The
 # immutable artifact name/document and historical jobs prove IaC source attempt1.
 def payload(aid,name,filename):return json.loads(reader.artifact_file(REPO,aid,run_id,2,name,filename,SOURCE))
 summary=payload(summary_id,f'iac-summary-{run_id}-1','summary.json')
 inventories=payload(summary_id,f'iac-summary-{run_id}-1','inventory.json')
 context=summary.get('context',{})
 require(context.get('run_id')==str(run_id) and context.get('run_attempt')=='1' and context.get('workflow_sha')==SOURCE and context.get('gitops_sha')==PLATFORM and context.get('iac_sha')==IAC and context.get('workflow_ref')=='ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-host-lifecycle.yml@refs/heads/main','original owner document provenance mismatch')
 require(all(r.get('run_attempt')=='1' and r.get('run_id')==str(run_id) and r.get('workflow_sha')==SOURCE and r.get('iac_sha')==IAC and r.get('result')=='applied_verified' for r in summary.get('receipts',[])),'resource receipt identity mismatch')
 handoff=load('existing_dev_handoff',Path(__file__).parents[1]/'dev-bootstrap-handoff/handoff.py')
 raw,instance=handoff.select(summary,inventories,summary['deploy_matrix'])
 require(instance=='109277144','not the authorized Dev instance')
 bootstrap=payload(bootstrap_id,f'dev-k3s-bootstrap-{run_id}-2','receipt.json')
 digest=hashlib.sha256(raw.encode()).hexdigest()
 require(bootstrap.get('schema_version')==1 and bootstrap.get('result')=='PASS' and bootstrap.get('environment')=='dev' and bootstrap.get('instance_id')==instance and bootstrap.get('run_id')==str(run_id) and bootstrap.get('cmdb_sha256')==digest and bootstrap.get('playbooks_sha')==PLAYBOOKS,'bootstrap receipt binding mismatch')
 require(all(bootstrap.get(k) is True for k in ('node_ready','source_ready','root_ready')) and bootstrap.get('node')=='dev-k3s-v5' and bootstrap.get('hostname')=='dev-k3s-v5','bootstrap target not Ready')
 require(bootstrap.get('gitops_sha')==PLATFORM and bootstrap.get('source_revision')=='sha1:'+PLATFORM and bootstrap.get('applied_revision')=='sha1:'+PLATFORM,'bootstrap protected platform mismatch')
 require(bootstrap.get('node_info',{}).get('kubeletVersion')=='v1.37.1+k3s1' and bootstrap.get('node_info',{}).get('architecture')=='amd64','bootstrap runtime mismatch')
 for k in ('node_uid','cluster_uid'):require(re.fullmatch('[0-9a-f-]{36}',bootstrap.get(k,'')),'bootstrap UID missing')
 return raw,dict(instance_id=instance,cmdb_sha256=digest,node_uid=bootstrap['node_uid'],cluster_uid=bootstrap['cluster_uid'],platform_sha=PLATFORM,source_run=run_id,iac_source_attempt=1,bootstrap_source_attempt=2,summary_artifact=summary_id,bootstrap_artifact=bootstrap_id)

def check_head(reader,sha,repo=GITOPS):
 checks=pages(reader,f'repos/{repo}/commits/{sha}/check-runs','check_runs')
 statuses=reader.api(f'repos/{repo}/commits/{sha}/status')
 require(checks and all(c.get('status')=='completed' and c.get('conclusion') in ('success','skipped','neutral') for c in checks),'candidate check not terminal successful/applicability-excluded')
 require(any(c.get('conclusion')=='success' for c in checks),'no successful candidate check')
 require(statuses.get('state')=='success' or (statuses.get('total_count')==0 and statuses.get('state')=='pending'),'candidate commit status failed/pending')
 return [{'name':c.get('name'),'conclusion':c.get('conclusion'),'id':c.get('id')} for c in checks]

def candidate(reader,number,stage):
 number=positive(number);require(stage in SCOPES,'fixed Dev stage required')
 pr=reader.api(f'repos/{GITOPS}/pulls/{number}')
 require(pr.get('number')==number and pr.get('base',{}).get('repo',{}).get('full_name')==GITOPS and pr.get('head',{}).get('repo',{}).get('full_name')==GITOPS and pr.get('base',{}).get('ref')=='main','same-repository main-based GitOps PR required')
 main=reader.api(f'repos/{GITOPS}/git/ref/heads/main')['object']['sha']
 head=pr.get('head',{}).get('sha');require(SHA.fullmatch(head or '') and SHA.fullmatch(main),'immutable candidate identity missing')
 if stage=='sit':
  require(pr.get('state')=='open' and not pr.get('merged'),'SIT requires unmerged candidate PR')
  comparison=reader.api(f'repos/{GITOPS}/compare/{main}...{head}')
  require(comparison.get('status') in ('ahead','identical'),'candidate must contain current main ancestry')
 else:
  require(pr.get('merged') is True and pr.get('state')=='closed','UAT requires merged PR')
  merged=pr.get('merge_commit_sha');require(SHA.fullmatch(merged or ''),'merged identity missing')
  comparison=reader.api(f'repos/{GITOPS}/compare/{merged}...{main}')
  require(comparison.get('status') in ('ahead','identical'),'merged PR not reachable from current main');head=main
 checks=check_head(reader,head)
 path=f'services/distributed-web-saas-fullstack/dev/{SCOPES[stage]}/release.yaml'
 content=reader.api(f'repos/{GITOPS}/contents/{path}?ref={head}')
 require(content.get('path')==path and content.get('type')=='file' and content.get('encoding')=='base64' and 0<content.get('size',0)<100000,'fixed release declaration missing/oversized')
 release=yaml.safe_load(base64.b64decode(content['content']))
 return {'schema_version':'dev-feature-candidate/v1','result':'verified','repository':GITOPS,'stage':stage,'candidate_pr':number,'candidate_head':head,'pr_head':pr['head']['sha'],'base_ref':'main','base_sha':main,'checks':'success','check_receipts':checks,'same_repository':True,'main_ancestry_verified':True,'source':{'workflow_ref':WORKFLOW,'run_id':os.environ['GITHUB_RUN_ID']}},release

def source_gate(reader,repo,sha,workflow):
 main=reader.api(f'repos/{repo}/git/ref/heads/main')['object']['sha']
 require(SHA.fullmatch(main),'source main identity missing')
 compared=reader.api(f'repos/{repo}/compare/{sha}...{main}')
 if compared.get('status') in ('ahead','identical'):return {'kind':'reachable_main','main_sha':main}
 prs=pages(reader,f'repos/{repo}/commits/{sha}/pulls')
 selected=[p for p in prs if p.get('state')=='open' and p.get('head',{}).get('sha')==sha and p.get('head',{}).get('repo',{}).get('full_name')==repo and p.get('base',{}).get('repo',{}).get('full_name')==repo and p.get('base',{}).get('ref')=='main']
 require(len(selected)==1,'source must be reachable main or one same-repository open PR head')
 require(reader.api(f'repos/{repo}/compare/{main}...{sha}').get('status') in ('ahead','identical'),'source PR lacks current main ancestry')
 def blob(ref):return reader.api(f'repos/{repo}/contents/{workflow}?ref={ref}').get('sha')
 baseline_blob=blob(main);candidate_blob=blob(sha)
 require(SHA.fullmatch(baseline_blob or '') and baseline_blob==candidate_blob,'candidate modified privileged publisher workflow; separate owner review required')
 return {'kind':'verified_source_pr','pr':selected[0]['number'],'main_sha':main,'checks':check_head(reader,sha,repo)}

PUBLISH={
 'caddy':('Build caddy image with cloudflare dns','Run actions/checkout@v7','Push image'),
 'console':('Build','Check Out Repository','Publish Frontend Image'),
 'accounts':('Publish GitHub Container Registry','Check Out Repository','Push Accounts image to GHCR'),
 'billing':('build','Run actions/checkout@v4','Build and push'),
 'content':('Build','Check out repository','Build and push service image'),
 'postgresql':('build-and-push-images (build-push-ghcr-image-postgresql,','Check Out Repository','Build And Push Image')}

def step_text(log,step):
 require(step.get('status')=='completed' and step.get('conclusion')=='success','publisher step not successful')
 start=datetime.datetime.fromisoformat(step['started_at'].replace('Z','+00:00'));end=datetime.datetime.fromisoformat(step['completed_at'].replace('Z','+00:00'))
 selected=[]
 for line in log.splitlines():
  match=re.match(r'^(\d{4}-\d\d-\d\dT[0-9:.]+Z) (.*)$',line)
  if match and start<=datetime.datetime.fromisoformat(match[1].replace('Z','+00:00'))<end+datetime.timedelta(seconds=1):selected.append(match[2])
 require(selected,'publisher step log unavailable');return '\n'.join(selected)

def verify_publish_log(component,job,log,sha,image):
 _,checkout,publish=PUBLISH[component]
 def one(name):
  selected=[s for s in job.get('steps',[]) if s.get('name')==name];require(len(selected)==1,'exact publisher step missing');return selected[0]
 checkout_log=step_text(log,one(checkout))
 # The checkout action emits full git-log HEAD after actual checkout. A fetch
 # argument alone is not proof that this revision became the build workspace.
 require(re.search(r'git log -1 --format=%H[^\n]*\n(?:[^\n]*\n){0,2}'+re.escape(sha)+r'(?:\n|$)',checkout_log),'actual checked-out source not proven')
 publish_log=step_text(log,one(publish));repo,digest=image.split('@')
 # Buildx publisher must finish the immutable source tag's manifest push; plain
 # digest occurrence, unrelated repository, export-only or failed push is rejected.
 buildx=re.search(r'pushing manifest for '+re.escape(repo)+r':sha-'+re.escape(sha)+r'@'+re.escape(digest)+r'[^\n]*done(?:\n|$)',publish_log)
 docker=re.search(r'(?m)^sha-'+re.escape(sha)+r': digest: '+re.escape(digest)+r' size: [0-9]+\s*$',publish_log)
 if component=='caddy':
  docker=any(re.search(r'(?m)^'+re.escape(sha[:length])+r': digest: '+re.escape(digest)+r' size: [0-9]+\s*$',publish_log) for length in range(7,41))
 require(bool(buildx) or (bool(docker) and 'The push refers to repository ['+repo+']' in publish_log),'exact image/source-tag successful push not proven')
 return {'kind':'authenticated_publisher_job_log','job_id':job['id'],'job_name':job['name'],'checkout_step':checkout,'publish_step':publish,'log_sha256':hashlib.sha256(log.encode()).hexdigest(),'source_sha':sha,'image':image}

def job_log_from_archive(archive,job_name):
 require(isinstance(archive,bytes) and len(archive)<=2_000_000,'oversized run logs archive')
 with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
  entries=zipped.infolist()
  require(len(entries)<=100 and sum(x.file_size for x in entries)<=4_000_000,'oversized run logs content')
  for item in entries:
   path=Path(item.filename)
   require(not path.is_absolute() and '..' not in path.parts and '\\' not in item.filename and (item.external_attr>>16)&0o170000!=0o120000 and not item.flag_bits&1,'unsafe run logs archive')
  matches=[x for x in entries if re.fullmatch(r'[0-9]+_'+re.escape(job_name.replace('/','_'))+r'\.txt',x.filename)]
  require(len(matches)==1 and matches[0].file_size<=2_000_000,'exact publisher job log missing or ambiguous')
  return zipped.read(matches[0])

def publisher_proof(reader,component,repo,rid,sha,image):
 profile=PUBLISH[component];jobs=pages(reader,f'repos/{repo}/actions/runs/{rid}/jobs','jobs')
 selected=[j for j in jobs if (j.get('name','').startswith(profile[0]) if component=='postgresql' else j.get('name')==profile[0]) and j.get('conclusion')=='success']
 require(len(selected)==1,'unique successful reviewed publisher job missing for '+component)
 job=selected[0];raw=None
 for attempt in range(1):
  try:raw=reader.api(f'repos/{repo}/actions/jobs/{job["id"]}/logs',binary=True);break
  except Exception:
   break
 if raw is None:
  archive=reader.api(f'repos/{repo}/actions/runs/{rid}/logs',binary=True)
  raw=job_log_from_archive(archive,job['name'])
 require(isinstance(raw,bytes) and len(raw)<=2_000_000,'publisher logs exceed bounded transport')
 return verify_publish_log(component,job,raw.decode(),sha,image)

def build_matrix(reader,release):
 matrix=[]
 for component,(repo,image_repo,workflow) in COMPONENTS.items():
  row=release[component];annotations=row['podAnnotations'];sha=annotations['release.svc.plus/source_sha'];rid=positive(annotations['release.svc.plus/build_run_id'])
  image=row['singleContainer']['image'] if component=='console' else row['workload']['image'] if component in ('accounts','billing','content') else row['image']
  require(SHA.fullmatch(sha) and annotations['release.svc.plus/source_repository']==repo and re.fullmatch('ghcr.io/'+re.escape(image_repo)+'@sha256:[0-9a-f]{64}',image),'component source/image outside allowlist')
  require(annotations['release.svc.plus/image_digest']==image.split('@')[1],'component digest annotation differs')
  run=reader.api(f'repos/{repo}/actions/runs/{rid}');run_identity(run,repo,sha,workflow)
  source_proof=source_gate(reader,repo,sha,workflow)
  # Prefer the existing source-owned image manifest. No Docker record or bare
  # annotation is promoted to a build proof when that producer manifest is absent.
  artifacts=pages(reader,f'repos/{repo}/actions/runs/{rid}/artifacts','artifacts')
  prefix={'console':'portal','content':'content-service','billing':'billing-service'}.get(component,component)
  name=f'{prefix}-main-image-{rid}-{run["run_attempt"]}'
  selected=[a for a in artifacts if a.get('name')==name]
  if not selected:
   proof=publisher_proof(reader,component,repo,rid,sha,image)
   matrix.append(dict(proof,component=component,repository=repo,run_id=rid,attempt=run['run_attempt'],source_gate=source_proof))
   continue
  require(len(selected)==1,'ambiguous source-owned main image manifests')
  aid=selected[0]['id'];payload=reader.artifact_file(repo,aid,rid,run['run_attempt'],name,'main-image-build.json',sha);proof=json.loads(payload)
  require(proof.get('schema')=='main-image-build/v1' and proof.get('source_repository')==repo and proof.get('source_sha')==sha and proof.get('image')==image and str(proof.get('run_id'))==str(rid) and str(proof.get('attempt'))==str(run['run_attempt']) and proof.get('event')=='push' and proof.get('ref')=='refs/heads/main' and proof.get('platform')=='linux/amd64','source-owned image manifest mismatch')
  matrix.append({'component':component,'repository':repo,'source_sha':sha,'image':image,'run_id':rid,'attempt':run['run_attempt'],'artifact_id':aid,'document_sha256':hashlib.sha256(payload).hexdigest(),'source_gate':source_proof})
 return matrix

def main():
 require(os.environ.get('GITHUB_WORKFLOW_REF')==WORKFLOW,'protected main caller required')
 reader=load('hardened_shared_reader',Path(os.environ['EVIDENCE_ROOT'])/'.github/scripts/acceptance/migration_matrix.py')
 root=Path(os.environ['DESTINATION']);root.mkdir(parents=True,exist_ok=True)
 raw,identity=foundation(reader,os.environ['FOUNDATION_RUN'],os.environ['SUMMARY_ARTIFACT'],os.environ['BOOTSTRAP_ARTIFACT'])
 receipt,release=candidate(reader,os.environ['CANDIDATE_PR'],os.environ['STAGE'])
 receipt['builds']=build_matrix(reader,release)
 fresh,_=candidate(reader,os.environ['CANDIDATE_PR'],os.environ['STAGE'])
 require(fresh['candidate_head']==receipt['candidate_head'] and fresh['base_sha']==receipt['base_sha'],'candidate/main moved during resolution')
 (root/'cmdb').mkdir(exist_ok=True);(root/'candidate').mkdir(exist_ok=True)
 (root/'cmdb/cmdb.json').write_text(raw)
 body=json.dumps(receipt,sort_keys=True)+'\n';(root/'candidate/receipt.json').write_text(body)
 (root/'foundation.json').write_text(json.dumps(identity,sort_keys=True)+'\n')
 with open(os.environ['GITHUB_OUTPUT'],'a') as output:
  for key,value in dict(identity,gitops_sha=receipt['candidate_head'],candidate_sha256=hashlib.sha256(body.encode()).hexdigest()).items():output.write(f'{key}={value}\n')
if __name__=='__main__':
 try:main()
 except Exception as error:raise SystemExit('Dev candidate resolution blocked: '+(str(error) if type(error) is ValueError else type(error).__name__)) from None
