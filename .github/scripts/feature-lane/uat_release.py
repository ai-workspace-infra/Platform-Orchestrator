#!/usr/bin/env python3
"""One Accounts main-build → complete Dev UAT release PR. No deployment or main write."""
import argparse
import base64
import copy
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import yaml

GITOPS = 'ai-workspace-infra/gitops'
RELEASE_PATH = 'services/distributed-web-saas-fullstack/dev/uat/release.yaml'
PREFIX = 'release.svc.plus/'
REPOS = {'caddy':'ai-workspace-infra/artifacts', 'console':'ai-workspace-services/portal',
         'accounts':'ai-workspace-services/accounts', 'billing':'ai-workspace-services/billing-service',
         'content':'ai-workspace-services/content-service', 'postgresql':'ai-workspace-services/postgresql'}
IMAGES = {'caddy':'ghcr.io/ai-workspace-infra/caddy-cloudflare', 'console':'ghcr.io/ai-workspace-services/console',
          'accounts':'ghcr.io/ai-workspace-services/accounts','billing':'ghcr.io/ai-workspace-services/billing-service',
          'content':'ghcr.io/ai-workspace-services/docs','postgresql':'ghcr.io/ai-workspace-services/postgresql'}


class Blocked(ValueError): pass


def require(condition, reason):
    if not condition: raise Blocked(reason)


def sha(value):
    return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{40}',value) is not None


def adapter():
    # PR1454 supplies this shared authenticated bounded artifact/run reader.
    # Do not vendor a third transport or silently fall back to caller evidence.
    path=Path(__file__).with_name('trusted.py')
    require(path.exists(),'dependency #1454 trusted artifact adapter must land first')
    spec=importlib.util.spec_from_file_location('uat_shared_trusted',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def image_slot(component, values):
    if component in ('caddy','postgresql'):return values
    return values['singleContainer' if component=='console' else 'workload']


def validate_release(doc):
    require(isinstance(doc,dict) and set(doc)==set(REPOS),'exact six-component release overlay required')
    for component,repo in REPOS.items():
        value=doc[component];annotations=value['podAnnotations'];image=image_slot(component,value)['image']
        require(annotations[PREFIX+'source_repository']==repo and sha(annotations[PREFIX+'source_sha']), 'unapproved baseline source')
        require(re.fullmatch(r'[1-9][0-9]*',str(annotations[PREFIX+'build_run_id'])) is not None,'baseline build identity required')
        digest=annotations[PREFIX+'image_digest']
        require(isinstance(digest,str) and re.fullmatch(r'sha256:[a-f0-9]{64}',digest) is not None,'immutable baseline digest required')
        require(image==IMAGES[component]+'@'+digest,'baseline image/annotation differs')
        if component in ('accounts','billing','content'):
            require(value['workload']['env']['IMAGE']==image,'runtime IMAGE differs from workload image')


def update_release(doc, proof):
    validate_release(doc)
    require(proof.get('schema')=='main-image-build/v1' and proof.get('source_repository')==REPOS['accounts']
            and sha(proof.get('source_sha')) and proof.get('event')=='push' and proof.get('ref')=='refs/heads/main'
            and proof.get('platform')=='linux/amd64','unsupported Accounts main manifest')
    require(type(proof.get('run_id')) is int and proof['run_id']>0 and type(proof.get('attempt')) is int and proof['attempt']>0,'manifest run binding required')
    image=proof.get('image','')
    require(isinstance(image,str) and re.fullmatch(re.escape(IMAGES['accounts'])+r'@sha256:[a-f0-9]{64}',image) is not None,'immutable allowlisted image required')
    updated=copy.deepcopy(doc);account=updated['accounts'];annotation=account['podAnnotations']
    annotation.update({PREFIX+'source_repository':proof['source_repository'],PREFIX+'source_sha':proof['source_sha'],
                       PREFIX+'image_digest':image.split('@')[1],PREFIX+'build_run_id':str(proof['run_id'])})
    account['workload']['image']=image;account['workload']['env']['IMAGE']=image
    validate_release(updated)
    require(all(updated[key]==doc[key] for key in REPOS if key!='accounts'),'unchanged baselines must be preserved')
    fingerprint=hashlib.sha256(json.dumps(updated,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return updated,fingerprint


def branch(api, repo):
    record=api(f'repos/{repo}/branches/main')
    require(sha(record.get('commit',{}).get('sha')),'current main unavailable')
    if repo==GITOPS:require(record.get('protected') is True,'GitOps target main must remain protected')
    return record['commit']['sha']


def prepare(trusted, gitops_base, run_id, attempt, artifact_id):
    require(sha(gitops_base),'fixed GitOps base SHA required')
    require(all(type(value) is int and value>0 for value in (run_id,attempt,artifact_id)),'positive run/attempt/artifact selectors only')
    api=trusted.reader.api
    require(branch(api,GITOPS)==gitops_base,'stale GitOps base selector')
    source_sha=branch(api,REPOS['accounts'])
    run=api(f'repos/{REPOS["accounts"]}/actions/runs/{run_id}')
    require(run.get('head_branch')=='main' and run.get('head_sha')==source_sha and run.get('event')=='push'
            and run.get('path','').split('@')[0]=='.github/workflows/ci-pipeline.yml'
            and run.get('repository',{}).get('full_name')==REPOS['accounts']
            and run.get('head_repository',{}).get('full_name')==REPOS['accounts']
            and run.get('status')=='completed' and run.get('conclusion')=='success'
            and run.get('run_attempt')==attempt,'successful current main source run required; no fork/tag/dispatch fallback')
    proof,producer=trusted.artifact({'repository':REPOS['accounts'],'workflow':'.github/workflows/ci-pipeline.yml',
        'event':'push','sha':source_sha,'run_id':run_id,'attempt':attempt,'artifact_id':artifact_id,
        'artifact_name':f'accounts-main-image-{run_id}-{attempt}','filename':'main-image-build.json'})
    require(proof.get('source_sha')==source_sha and proof.get('run_id')==run_id and proof.get('attempt')==attempt,
            'downloaded manifest source/run/attempt differs')
    content=api(f'repos/{GITOPS}/contents/{RELEASE_PATH}?ref={gitops_base}')
    require(content.get('type')=='file' and content.get('path')==RELEASE_PATH and content.get('encoding')=='base64'
            and type(content.get('size')) is int and content['size']<=1_000_000,'fixed UAT release source unavailable')
    raw=base64.b64decode(content['content']);require(len(raw)<=1_000_000,'oversized release overlay')
    original=raw.decode();updated,fingerprint=update_release(yaml.safe_load(original),proof)
    output='# six-component-matrix-sha256: '+fingerprint+'\n'+yaml.safe_dump(updated,sort_keys=False)
    require(branch(api,REPOS['accounts'])==source_sha and branch(api,GITOPS)==gitops_base,'main advanced during evidence lookup; select a new candidate')
    patch=''.join(difflib.unified_diff(original.splitlines(True),output.splitlines(True),fromfile='a/'+RELEASE_PATH,tofile='b/'+RELEASE_PATH))
    return {'gitops_base':gitops_base,'source_sha':source_sha,'matrix_fingerprint':fingerprint,
            'run_id':run_id,'attempt':attempt,'artifact_id':artifact_id,'manifest_sha256':producer['document_sha256'],
            'content':output,'patch':patch}


def write_api(path, payload):
    # Same existing gh CLI authentication; mutation is GitHub PR construction only.
    allowed=(f'repos/{GITOPS}/git/blobs',f'repos/{GITOPS}/git/trees',f'repos/{GITOPS}/git/commits',
             f'repos/{GITOPS}/git/refs',f'repos/{GITOPS}/pulls')
    require(path in allowed,'only fixed GitOps proposal APIs are permitted')
    result=subprocess.run(['gh','api','--hostname','github.com','--method','POST',path,'--input','-'],
                          input=json.dumps(payload).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          check=True,timeout=60)
    require(len(result.stdout)<=1_000_000,'oversized GitHub proposal response')
    return json.loads(result.stdout)


def publish(trusted, plan, mutate=write_api):
    # Authenticate selectors again immediately before writes; caller cannot pass a fabricated plan.
    fresh=prepare(trusted,plan['gitops_base'],plan['run_id'],plan['attempt'],plan['artifact_id'])
    require(fresh==plan,'proposal no longer matches authenticated inputs')
    api=trusted.reader.api;base=plan['gitops_base']
    source=api(f'repos/{GITOPS}/git/commits/{base}')
    require(sha(source.get('tree',{}).get('sha')),'GitOps base tree unavailable')
    blob=mutate(f'repos/{GITOPS}/git/blobs',{'content':plan['content'],'encoding':'utf-8'})
    tree=mutate(f'repos/{GITOPS}/git/trees',{'base_tree':source['tree']['sha'],
        'tree':[{'path':RELEASE_PATH,'mode':'100644','type':'blob','sha':blob['sha']}]})
    commit=mutate(f'repos/{GITOPS}/git/commits',{'message':'Update Dev UAT Accounts from verified main build',
        'tree':tree['sha'],'parents':[base]})
    name=f'feature/dev-uat-accounts-{plan["run_id"]}-{plan["attempt"]}-{plan["matrix_fingerprint"][:12]}'
    require(branch(api,GITOPS)==base and branch(api,REPOS['accounts'])==plan['source_sha'],'main advanced before proposal branch creation')
    mutate(f'repos/{GITOPS}/git/refs',{'ref':'refs/heads/'+name,'sha':commit['sha']})
    require(branch(api,GITOPS)==base,'GitOps main advanced before PR; retain proposal branch for review')
    return mutate(f'repos/{GITOPS}/pulls',{'title':'Update Dev UAT Accounts from verified main build','base':'main','head':name,'draft':True,
        'body':f'Verified Accounts push/main build {plan["run_id"]} attempt {plan["attempt"]}, source {plan["source_sha"]}. '
               f'Base {base}; complete six-component matrix fingerprint {plan["matrix_fingerprint"]}. '
               'Other five component baselines are preserved. No deployment or business acceptance is claimed. '
               'Merge requires the existing review/check/authorization gates; this PR does not merge itself.'})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--gitops-base',required=True)
    for name in ('run-id','attempt','artifact-id'):parser.add_argument('--'+name,type=int,required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--open-pr',action='store_true')
    args=parser.parse_args()
    try:
        trusted=adapter();plan=prepare(trusted,args.gitops_base,args.run_id,args.attempt,args.artifact_id)
        # Default is local proposal only. Parent-controlled mutation requires explicit --open-pr.
        Path(args.output).write_text(plan['patch'])
        result={key:value for key,value in plan.items() if key not in ('content','patch')}
        if args.open_pr:result['pull_request']=publish(trusted,plan)['html_url']
        print(json.dumps(result,sort_keys=True))
    except Exception:
        raise SystemExit('Dev UAT proposal BLOCKED: missing trusted dependency/artifact, stale main selector or invalid release matrix.') from None

if __name__=='__main__':main()
