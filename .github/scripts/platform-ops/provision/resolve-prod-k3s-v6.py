#!/usr/bin/env python3
"""Validate the separate fresh V6 request before credentials or mutation."""
import json
import os
from pathlib import Path
import re
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[4]


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def requested_refs(inputs):
    try:
        refs = json.loads(inputs.get('source_ref', ''))
    except (TypeError, ValueError):
        raise ValueError('V6 source_ref requires JSON keys gitops, playbooks and iac') from None
    require(isinstance(refs, dict) and set(refs) == {'gitops', 'playbooks', 'iac'},
            'V6 source_ref requires exactly gitops, playbooks and iac')
    for key, value in refs.items():
        require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', value),
                'Invalid selected ref: ' + key)
        require('..' not in value and not re.fullmatch(r'[0-9a-f]{40}', value),
                'Select a branch or tag for ' + key)
    require(re.fullmatch(r'v[0-9][A-Za-z0-9._-]*', refs['gitops']),
            'V6 GitOps selection requires an immutable reviewed tag')
    return refs


def resolve_owner(checkout, requested):
    """Resolve metadata only; never execute code from the selected checkout."""
    checkout = Path(checkout).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(checkout), *args],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    if requested.startswith('refs/heads/'):
        candidates = ['refs/remotes/origin/' + requested.removeprefix('refs/heads/')]
    elif requested.startswith('refs/tags/'):
        candidates = [requested]
    else:
        require(not requested.startswith('refs/'), 'Unsupported owner ref namespace')
        candidates = ['refs/remotes/origin/' + requested, 'refs/tags/' + requested]
    resolved = []
    for ref in candidates:
        try:
            resolved.append(git('rev-parse', '--verify', ref + '^{commit}'))
        except subprocess.CalledProcessError:
            pass
    require(len(resolved) == 1, 'Owner ref is missing or ambiguous; use refs/heads/ or refs/tags/')
    sha = resolved[0]
    require(re.fullmatch(r'[0-9a-f]{40}', sha), 'Owner SHA is invalid')
    require(git('rev-parse', 'HEAD') == sha, 'Owner checkout differs from selected ref')
    require(not git('status', '--porcelain', '--untracked-files=all'), 'Dirty owner checkout')
    try:
        git('merge-base', '--is-ancestor', sha, 'refs/remotes/origin/main')
    except subprocess.CalledProcessError:
        raise ValueError('Production owner commit must be merged into main') from None
    return sha


def validate(inputs, config, checkout, ref):
    require(re.fullmatch(r'refs/tags/v6\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?', ref), 'V6 production dispatch requires a reviewed release tag')
    fixed = {'vault_env_path':'prod-v6','cloud_provider':'akamai-cloud','cloud_account':'manbuzhe2026',
             'instance_plan':'2C4G','target_domains':'web-saas','dns_mode':'none','open_platform_service':'none',
             'offline_mode':'off','runner_type':'ubuntu-latest'}
    for key, value in fixed.items():
        require(inputs.get(key) == value, 'V6 input mismatch: ' + key)
    require(inputs.get('operation') in ('plan','infra','deploy'), 'V6 excludes data migration, initialization and destroy')
    require(inputs.get('include_external_agent_proxy') in (False, 'false'), 'External nodes are outside V6 scope')
    require(inputs.get('skip_stripe_catalog') in (True,'true'), 'V6 bootstrap must skip billing synchronization')
    require(inputs.get('akamai_account','') in ('','manbuzhe2026'), 'Conflicting account selector')
    for key in ('existing_target_host','deploy_tag','xray_exporter_image','agent_controller_url','vault_addr'):
        require(not inputs.get(key), 'V6 does not accept override: ' + key)
    tag = requested_refs(inputs)['gitops']
    decl = yaml.safe_load((checkout/config['resource_manifest']).read_text())
    g=decl['global']
    require((g['provider'],g['environment'],g['account'],g['workspace'],g['state_namespace']) ==
            ('akamai-cloud','prod','manbuzhe2026','prod-k3s-v6','prod-k3s-v6'), 'Wrong resource identity')
    require(g['prevent_destroy'] is True and len(decl['hosts'])==1, 'Expected one protected candidate')
    host=decl['hosts'][0]
    require((host['name'],host['type'],host['region'],host['image'])==('prod-k3s-v6','g6-standard-2','jp-tyo-3','linode/debian13'), 'Node plan differs')
    require(host['volume']=={'label':'prod-k3s-v6-data','size':100,'filesystem':'ext4'}, 'Independent data volume differs')
    fw=host['firewall']
    require(fw['ssh_cidrs']==['0.0.0.0/0'] and fw['ssh_ipv6_cidrs']==[] and fw['additional_tcp_ports']==[], 'Unreviewed exposure')
    hv=host['host_vars']
    require(hv['public_dns_cutover'] is False and hv['reserved_dns_aliases']=={}, 'DNS cutover is forbidden')
    require(hv['target_generation']=='prod-v6' and hv['k3s_platform_flux_bootstrap_mode']=='declarative_paused', 'Wrong bootstrap mode')
    require(hv['k3s_platform_flux_root_name']==config['flux_root_name'] and hv['k3s_platform_write_kubeconfig_mode']=='0600', 'Wrong Flux root or administrator permissions')
    require(hv['k3s_platform_local_storage_path']=='/data/k3s/storage' and hv['k3s_platform_require_data_mount'] is True, 'Data mount required')
    target=yaml.safe_load((checkout/config['target_manifest']).read_text())['targets']
    require(len(target)==1, 'One V6 target required')
    resource=target[0]['stages']['resources']
    require(resource['manifest']==config['resource_manifest'] and resource['create_only'] is True and resource['requires_existing_state'] is False and resource['destroy_allowed'] is False, 'Creation safety contract differs')
    objects=[]
    for folder in [checkout/config['root_path'],*(checkout/'services/prod-k3s-v6').iterdir()]:
        for path in folder.glob('*.yaml'):
            objects.extend(o for o in yaml.safe_load_all(path.read_text()) if isinstance(o,dict))
    expected={'GitRepository':6,'Kustomization':9,'HelmRelease':8}
    for kind,count in expected.items():
        selected=[o for o in objects if o.get('kind')==kind and 'toolkit.fluxcd.io/' in o.get('apiVersion','')]
        require(len(selected)==count, 'Wrong V6 object count: '+kind)
        for obj in selected:
            require(obj['spec'].get('suspend') is True, 'All V6 bootstrap objects must start paused')
            if kind=='GitRepository':
                require(obj['spec']['url']=='https://github.com/ai-workspace-infra/gitops.git' and obj['spec']['ref']=={'tag':tag}, 'Initial sources must bind the reviewed tag')
            if kind=='Kustomization':
                path=(checkout/obj['spec']['path'].removeprefix('./')).resolve()
                require(path.is_relative_to(checkout.resolve()) and path.is_dir(), 'Missing or escaped source path')
    roots=[o for o in objects if o.get('kind')=='Kustomization'
           and o.get('metadata',{}).get('namespace')=='flux-system'
           and o.get('metadata',{}).get('name')==config['flux_root_name']]
    require(len(roots)==1, 'Expected exactly one stable environment root')
    root=roots[0]
    require(root['spec'].get('path')=='./'+config['root_path']
            and root['spec'].get('sourceRef')=={'kind':'GitRepository','name':'config-prod'},
            'Flux root must select the configured batch path and management source')
    return inputs['operation']


def main():
    inputs=json.loads(os.environ['V6_INPUTS'])
    refs=requested_refs(inputs)
    if os.environ.get('V6_RESOLVE_REFS') == 'true':
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:
            for key,value in refs.items():
                out.write(f'{key}_ref={value}\n')
        return
    config=yaml.safe_load((ROOT/'.github/config/prod-k3s-v6.yaml').read_text())
    checkout=Path(os.environ['V6_GITOPS']).resolve()
    require(os.environ.get('GITHUB_REF_PROTECTED') == 'true', 'V6 release tag must be protected')
    mode=validate(inputs,config,checkout,os.environ['GITHUB_REF'])
    sha=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
    pinned=subprocess.check_output(['git','-C',str(checkout),'rev-parse','refs/tags/'+refs['gitops']+'^{commit}'],text=True).strip()
    require(sha==pinned, 'GitOps tag and checkout differ')
    require(not subprocess.check_output(['git','-C',str(checkout),'status','--porcelain'],text=True).strip(), 'Dirty GitOps checkout')
    owners={name+'_sha': resolve_owner(os.environ['V6_'+name.upper()], refs[name])
            for name in ('iac','playbooks')}
    declaration=yaml.safe_load((checkout/config['resource_manifest']).read_text())
    scope=declaration['global']
    vault=config['bootstrap_vault']
    require(all(isinstance(vault.get(key), str) and vault[key] and not any(c in vault[key] for c in '\n\r;')
                for key in ('address','role','ssh_record','provider_record')), 'Invalid bootstrap Vault binding')
    outputs=dict({k:v for k,v in config.items() if k != 'bootstrap_vault'},**owners,
                 environment=scope['environment'],account=scope['account'],
                 selectors=json.dumps({k:scope[v] for k,v in {'environment':'environment','provider':'provider',
                                      'account':'account','namespace':'state_namespace'}.items()},separators=(',',':')),
                 vault_address=vault['address'],vault_role=vault['role'],
                 ssh_record=vault['ssh_record'],provider_record=vault['provider_record'],
                 gitops_sha=sha,action='plan' if mode=='plan' else 'apply',operation=mode,
                 **{name+'_ref': value for name,value in refs.items()})
    with open(os.environ['GITHUB_OUTPUT'],'a') as out:
        for key,value in outputs.items():
            require('\n' not in str(value), 'Multiline output rejected')
            out.write(f'{key}={value}\n')
    print(json.dumps(outputs,sort_keys=True))


if __name__=='__main__': main()
