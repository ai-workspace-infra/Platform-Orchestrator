"""Control-plane offline falsification; fixtures are not live acceptance."""
import copy,importlib.util,json,os,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('resolve',ROOT/'.github/actions/dev-feature-resolve/resolve.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
FIX=Path(__file__).with_name('fixtures')/'dev-feature-foundation'

class Reader:
 def __init__(self):self.summary=json.loads((FIX/'summary.json').read_text());self.boot=json.loads((FIX/'receipt.json').read_text());self.calls=[]
 def api(self,path,binary=False):
  self.calls.append(path)
  if '/attempts/1/jobs' in path:return {'jobs':[{'name':'iac / summary','conclusion':'success'},{'name':'iac / resources (dev-akamai-dev-k3s-v5, provider) / resources','conclusion':'success'}]}
  if '/attempts/2/jobs' in path:return {'jobs':[{'name':'bootstrap / bootstrap','conclusion':'success'}]}
  run={'repository':{'full_name':R.REPO},'head_repository':{'full_name':R.REPO},'head_sha':R.SOURCE,'path':'.github/workflows/dev-host-lifecycle.yml','event':'workflow_dispatch','head_branch':'main','run_attempt':2,'status':'completed','conclusion':'success'}
  if path.endswith('/attempts/1'):run.update(run_attempt=1,conclusion='failure')
  return run
 def artifact_file(self,repo,aid,rid,transport_attempt,name,filename,sha):
  assert transport_attempt==2
  if filename=='summary.json':return json.dumps(self.summary).encode()
  if filename=='receipt.json':return json.dumps(self.boot).encode()
  return (FIX/'inventory.json').read_bytes()

class FoundationTests(unittest.TestCase):
 def test_actual_owner_bundle_reuses_handoff_and_preserves_attempts(self):
  reader=Reader();raw,identity=R.foundation(reader,40353330431,12664517641,12668512699)
  self.assertEqual(identity['instance_id'],'109277144');self.assertEqual(identity['iac_source_attempt'],1);self.assertEqual(identity['bootstrap_source_attempt'],2)
  self.assertEqual(set(json.loads(raw)),{'dev-k3s-v5'});self.assertTrue(any('/attempts/1/jobs' in p for p in reader.calls))
 def test_original_context_and_target_tampering_fail(self):
  for mutate in [lambda r:r.summary['context'].update(run_attempt='2'),lambda r:r.boot.update(instance_id='other'),lambda r:r.boot.update(cmdb_sha256='0'*64),lambda r:r.boot.update(root_ready=False)]:
   reader=Reader();mutate(reader)
   with self.assertRaises(ValueError):R.foundation(reader,40353330431,12664517641,12668512699)
 def test_bool_locator_rejected(self):
  with self.assertRaises(ValueError):R.positive(True)

class PublisherTests(unittest.TestCase):
 def fixture(self):
  sha='a'*40;image='ghcr.io/ai-workspace-services/billing-service@sha256:'+'b'*64
  job={'id':1,'name':'build','steps':[{'name':'Run actions/checkout@v4','status':'completed','conclusion':'success','started_at':'2026-10-27T00:00:00Z','completed_at':'2026-10-27T00:00:02Z'},{'name':'Build and push','status':'completed','conclusion':'success','started_at':'2026-10-27T00:00:05Z','completed_at':'2026-10-27T00:00:10Z'}]}
  log='2026-10-27T00:00:01.000Z [command]/usr/bin/git log -1 --format=%H\n2026-10-27T00:00:01.100Z '+sha+'\n2026-10-27T00:00:08.000Z #1 pushing manifest for '+image.split('@')[0]+':sha-'+sha+'@'+image.split('@')[1]+' 1.0s done\n'
  return sha,image,job,log
 def test_exact_publisher_step_source_tag_and_digest(self):
  sha,image,job,log=self.fixture();proof=R.verify_publish_log('billing',job,log,sha,image)
  self.assertEqual(proof['job_id'],1)
 def test_unrelated_digest_or_export_or_failed_push_rejected(self):
  sha,image,job,log=self.fixture()
  for changed in [log.replace('1.0s done','failed'),log.replace(':sha-'+sha,':latest'),log.replace('pushing manifest for','exporting manifest for'),log.replace('billing-service','other-service'),log.replace('00:00:08.000','00:00:15.000'),log.replace('git log -1 --format=%H','git fetch '+sha)]:
   with self.assertRaises(ValueError):R.verify_publish_log('billing',job,changed,sha,image)
 def test_two_candidate_images_use_same_policy(self):
  sha,image,job,log=self.fixture()
  for source,digest in [('a','b'),('c','d')]:
   changed=log.replace(sha,source*40).replace('b'*64,digest*64)
   self.assertEqual(R.verify_publish_log('billing',job,changed,source*40,image.replace('b'*64,digest*64))['source_sha'],source*40)

class ArchiveTests(unittest.TestCase):
 def test_large_unread_precheck_does_not_expand_beyond_selected_job_bound(self):
  import io,zipfile
  stream=io.BytesIO()
  with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as z:
   z.writestr('0_Precheck.txt','synthetic-noise' * 400000)
   z.writestr('1_Build.txt','selected-public-log')
  self.assertEqual(R.job_log_from_archive(stream.getvalue(),'Build'),b'selected-public-log')
 def test_exact_job_archive_and_traversal_rejection(self):
  import io,zipfile
  def archive(entries):
   stream=io.BytesIO()
   with zipfile.ZipFile(stream,'w') as z:
    for name,body in entries:z.writestr(name,body)
   return stream.getvalue()
  self.assertEqual(R.job_log_from_archive(archive([('1_Build.txt','synthetic')]),'Build'),b'synthetic')
  for entries in [[('../Build.txt','bad')],[('1_Other.txt','bad')],[('1_Build.txt','one'),('2_Build.txt','two')]]:
   with self.assertRaises(ValueError):R.job_log_from_archive(archive(entries),'Build')
 def test_caddy_old_source_tag_is_bound_to_full_checkout(self):
  sha,image,job,log=PublisherTests().fixture();image=image.replace('ai-workspace-services/billing-service','ai-workspace-infra/caddy-cloudflare')
  job['name']='Build caddy image with cloudflare dns';job['steps'][0]['name']='Run actions/checkout@v7';job['steps'][1]['name']='Push image'
  log=log.split('2026-10-27T00:00:08')[0]+'2026-10-27T00:00:08.000Z The push refers to repository [ghcr.io/ai-workspace-infra/caddy-cloudflare]\n2026-10-27T00:00:08.100Z '+sha[:7]+': digest: sha256:'+'b'*64+' size: 100\n'
  self.assertEqual(R.verify_publish_log('caddy',job,log,sha,image)['source_sha'],sha)
  with self.assertRaises(ValueError):R.verify_publish_log('caddy',job,log.replace(sha[:7]+': digest','latest: digest'),sha,image)

class CandidateTests(unittest.TestCase):
 def test_same_repository_main_ancestry_and_current_head(self):
  class API:
   def __init__(self):self.sha='a'*40;self.fork=False;self.state='ahead'
   def api(self,path):
    if '/pulls/' in path:return {'number':605,'head':{'sha':self.sha,'repo':{'full_name':'fork/repo' if self.fork else R.GITOPS}},'base':{'repo':{'full_name':R.GITOPS},'ref':'main'},'state':'open','merged':False}
    if '/git/ref/' in path:return {'object':{'sha':'b'*40}}
    if '/compare/' in path:return {'status':self.state}
    if '/check-runs' in path:return {'check_runs':[{'name':'test','status':'completed','conclusion':'success','id':1}]}
    if path.endswith('/status'):return {'state':'pending','total_count':0}
    import base64
    fixed='services/distributed-web-saas-fullstack/dev/sit-xconnect-referral/release.yaml'
    return {'path':fixed,'type':'file','encoding':'base64','size':2,'content':base64.b64encode(b'{}').decode()}
  api=API()
  with patch.dict(os.environ,{'GITHUB_RUN_ID':'123'}):
   for sha in ('a'*40,'c'*40):api.sha=sha;self.assertEqual(R.candidate(api,605,'sit')[0]['candidate_head'],sha)
   api.fork=True
   with self.assertRaises(ValueError):R.candidate(api,605,'sit')
   api.fork=False;api.state='diverged'
   with self.assertRaises(ValueError):R.candidate(api,605,'sit')

class PreviewTests(unittest.TestCase):
 def fixture(self):
  sha='a'*40;image='ghcr.io/ai-workspace-services/accounts@sha256:'+'b'*64
  steps=[]
  for number,name in [(1,'Resolve publish target'),(2,'Check Out Repository'),(3,'Load Vault Secrets for GHCR'),(4,'Compute GHCR image tags'),(5,'Push Accounts image to GHCR')]:
   steps.append({'name':name,'number':number,'status':'completed','conclusion':'success','started_at':f'2026-10-27T00:00:{number*3:02}Z','completed_at':f'2026-10-27T00:00:{number*3+1:02}Z'})
  steps.append({'name':'Push Accounts image to Artifact Registry','number':6,'conclusion':'skipped'})
  target='\n'.join('2026-10-27T00:00:03.100Z   '+k+': '+v for k,v in {'PUBLISH_TARGET':'github','PUSH_IMAGE':'true','EVENT_NAME':'workflow_dispatch','DEPLOY_ENV':'sit','SOURCE_REF':sha,'PUBLISH_ARTIFACT_REGISTRY':'false'}.items())
  log=target+'\n2026-10-27T00:00:06.100Z [command]/usr/bin/git log -1 --format=%H\n2026-10-27T00:00:06.200Z '+sha+'\n2026-10-27T00:00:09.100Z   role: github-actions-accounts-sit\n2026-10-27T00:00:12.100Z type=raw,value=latest,enable=false\n2026-10-27T00:00:15.100Z The push refers to repository [ghcr.io/ai-workspace-services/accounts]\n2026-10-27T00:00:15.200Z sha-'+sha+': digest: sha256:'+'b'*64+' size: 100\n'
  return sha,image,{'id':12,'name':'Publish GitHub Container Registry','steps':steps},log
 def test_sit_dispatch_exact_flags_role_and_push(self):
  sha,image,job,log=self.fixture();self.assertEqual(R.verify_publish_log('accounts',job,log,sha,image,True)['source_sha'],sha)
  for key,bad in [('DEPLOY_ENV: sit','DEPLOY_ENV: prod'),('role: github-actions-accounts-sit','role: github-actions-accounts-prod'),('PUBLISH_ARTIFACT_REGISTRY: false','PUBLISH_ARTIFACT_REGISTRY: true'),('latest,enable=false','latest,enable=true')]:
   with self.assertRaises(ValueError):R.verify_publish_log('accounts',job,log.replace(key,bad),sha,image,True)
 def test_preview_branch_task_and_open_pr_identity(self):
  sha='a'*40
  class API:
   def __init__(self):self.branch='feature/referral';self.body='Referral baseline #277';self.open=True;self.helper_mismatch=False
   def api(self,path):
    if '/git/ref/' in path:return {'object':{'sha':'c'*40}}
    if '/compare/'+sha in path:return {'status':'behind'}
    if '/compare/' in path:return {'status':'ahead'}
    if '/commits/' in path and '/pulls' in path:return [{'number':279,'state':'open' if self.open else 'closed','body':self.body,'head':{'sha':sha,'ref':self.branch,'repo':{'full_name':'ai-workspace-services/accounts'}},'base':{'ref':'main','repo':{'full_name':'ai-workspace-services/accounts'}}}]
    if '/pulls/277' in path:return {'number':277,'body':R.FEATURE_TASK_PATH}
    if '/contents/' in path:
     fixed=path.split('/contents/')[1].split('?')[0]
     return {'type':'file','path':fixed,'sha':(('f'*40 if self.helper_mismatch and sha in path else 'e'*40) if 'resolve-pipeline-flags.sh' in path else R.APPROVED_ACCOUNTS_PREVIEW_WORKFLOW_BLOB if sha in path else 'd'*40)}
    if '/check-runs' in path:return {'check_runs':[{'name':'test','status':'completed','conclusion':'success','id':1}]}
    if path.endswith('/status'):return {'state':'success','total_count':1}
    raise AssertionError(path)
  api=API();run={'event':'workflow_dispatch','head_branch':'feature/referral','head_sha':sha}
  self.assertEqual(R.source_gate(api,'ai-workspace-services/accounts',sha,'.github/workflows/ci-pipeline.yml','sit',run)['pr'],279)
  for stage,branch,body,opened in [('uat','feature/referral','baseline #277',True),('sit','other','baseline #277',True),('sit','feature/referral','unrelated',True),('sit','feature/referral','baseline #277',False)]:
   api.branch=branch;api.body=body;api.open=opened
   with self.assertRaises(ValueError):R.source_gate(api,'ai-workspace-services/accounts',sha,'.github/workflows/ci-pipeline.yml',stage,run)
  api.branch='feature/referral';api.body='baseline #277';api.open=True;api.helper_mismatch=True
  with self.assertRaises(ValueError):R.source_gate(api,'ai-workspace-services/accounts',sha,'.github/workflows/ci-pipeline.yml','sit',run)

class PriorOwnerTests(unittest.TestCase):
 def fixture(self):
  identity={'instance_id':'109277144','node_uid':'node','cluster_uid':'cluster','platform_sha':R.PLATFORM,'cmdb_sha256':'e'*64}
  source='a'*40;candidate='b'*40;owner='c'*40
  binding={'candidate_sha':candidate,'namespace':'feature-xconnect-referral-sit','node_uid':'node','cluster_uid':'cluster','instance_id':'109277144','manifest_sha256':'d'*64,'source':{'repository':R.REPO,'workflow_ref':R.WORKFLOW,'workflow_sha':source,'owner_sha':owner,'run_id':'123','run_attempt':'1'}}
  receipt={**identity,'candidate_sha':candidate,'namespace':binding['namespace'],'manifest_sha256':'d'*64,'schema_version':'dev-feature-flux/v1','mode':'prepare','result':'prepared','owner_sha':owner,'run_id':'123','run_attempt':'1','registry':{'result':'configured','namespace':binding['namespace'],'secret_name':'web-saas-registry','source_path':'kv/CICD/dev/ghcr','oci_mapping':{'schema_version':'dev-oci-platform/v1','images':{name:{} for name in R.COMPONENTS},'binding':binding}}}
  class API:
   def api(self,path):
    if '/git/ref/' in path:return {'object':{'sha':source}}
    if '/compare/' in path:return {'status':'identical'}
    if '/contents/' in path:return {'type':'file','sha':'f'*40}
    if '/artifacts/' in path:return {'name':'dev-feature-sit-prepare-123-1'}
    if '/jobs' in path:return {'jobs':[{'name':'deploy / lane','conclusion':'success'}]}
    return {'repository':{'full_name':R.REPO},'head_repository':{'full_name':R.REPO},'head_sha':source,'head_branch':'main','run_attempt':1,'path':'.github/workflows/dev-feature-deploy.yml','event':'workflow_dispatch','status':'completed','conclusion':'success'}
   def artifact_file(self,*args):return json.dumps(receipt).encode()
  return API(),receipt,identity,candidate,owner
 def test_authenticated_projection_preserves_bytes_and_original_producer(self):
  api,receipt,identity,candidate,owner=self.fixture()
  with patch.object(R,'owner_producer',return_value=owner):
   raw,proof=R.prior_owner_receipt(api,'feature',123,456,'sit','verify',identity,candidate)
   self.assertEqual(raw,json.dumps(receipt).encode());self.assertEqual(proof['source_attempt'],1)
   receipt['candidate_sha']='0'*40
   with self.assertRaises(ValueError):R.prior_owner_receipt(api,'feature',123,456,'sit','verify',identity,candidate)
 def test_self_declared_owner_or_missing_mapping_is_rejected(self):
  api,receipt,identity,candidate,owner=self.fixture()
  with patch.object(R,'owner_producer',return_value=owner):
   receipt['owner_sha']='f'*40
   with self.assertRaises(ValueError):R.prior_owner_receipt(api,'feature',123,456,'sit','verify',identity,candidate)
   receipt['owner_sha']=owner;receipt['registry']['oci_mapping']['images']={}
   with self.assertRaises(ValueError):R.prior_owner_receipt(api,'feature',123,456,'sit','verify',identity,candidate)

if __name__=='__main__':unittest.main()
