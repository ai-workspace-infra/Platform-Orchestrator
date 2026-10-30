import copy
import json
import importlib.util
from pathlib import Path
import tempfile
import subprocess
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('v6',ROOT/'.github/scripts/platform-ops/provision/resolve-prod-k3s-v6.py')
v6=importlib.util.module_from_spec(spec);spec.loader.exec_module(v6)

class RequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config={'resource_manifest':'resource.yaml','target_manifest':'target.yaml','root_path':'cluster','node':'prod-k3s-v6','flux_root_name':'prod-k3s'}
        self.inputs={'vault_env_path':'prod-v6','cloud_provider':'akamai-cloud','cloud_account':'manbuzhe2026','instance_plan':'2C4G','target_domains':'web-saas','dns_mode':'none','open_platform_service':'none','offline_mode':'off','runner_type':'ubuntu-latest','operation':'deploy','include_external_agent_proxy':False,'skip_stripe_catalog':True,'source_ref':'v1.0.0'}
        self.host={'name':'prod-k3s-v6','type':'g6-standard-2','region':'jp-tyo-3','image':'linode/debian13','volume':{'label':'prod-k3s-v6-data','size':100,'filesystem':'ext4'},'firewall':{'ssh_cidrs':['0.0.0.0/0'],'ssh_ipv6_cidrs':[],'additional_tcp_ports':[]},'host_vars':{'public_dns_cutover':False,'reserved_dns_aliases':{},'target_generation':'prod-v6','k3s_platform_flux_bootstrap_mode':'declarative_paused','k3s_platform_flux_root_name':'prod-k3s','k3s_platform_write_kubeconfig_mode':'0600','k3s_platform_local_storage_path':'/data/k3s/storage','k3s_platform_require_data_mount':True}}
        self.inputs['source_ref']=json.dumps({'gitops':'main','playbooks':'main','iac':'main'})
        self.decl={'global':{'provider':'akamai-cloud','environment':'prod','account':'manbuzhe2026','workspace':'prod-k3s-v6','state_namespace':'prod-k3s-v6','prevent_destroy':True},'hosts':[self.host]}
        (self.root/'resource.yaml').write_text(yaml.safe_dump(self.decl))
        target={'targets':[{'stages':{'resources':{'manifest':'resource.yaml','create_only':True,'requires_existing_state':False,'destroy_allowed':False}}}]}
        (self.root/'target.yaml').write_text(yaml.safe_dump(target))
        (self.root/'cluster').mkdir();(self.root/'services/prod-k3s-v6/unit').mkdir(parents=True)
        objects=[]
        for kind,n,api in [('GitRepository',6,'source'),('Kustomization',9,'kustomize'),('HelmRelease',8,'helm')]:
            for i in range(n):
                obj={'apiVersion':api+'.toolkit.fluxcd.io/v1','kind':kind,'metadata':{'name':kind+str(i)},'spec':{'suspend':True}}
                if kind=='GitRepository':obj['spec'].update(url='https://github.com/ai-workspace-infra/gitops.git',ref={'tag':'v1.0.0'})
                if kind=='Kustomization':obj['spec']['path']='./cluster'
                objects.append(obj)
        root=next(o for o in objects if o['kind']=='Kustomization')
        root['metadata'].update(name='prod-k3s',namespace='flux-system')
        root['spec']['sourceRef']={'kind':'GitRepository','name':'config-prod'}
        management=next(o for o in objects if o['kind']=='GitRepository')
        management['metadata'].update(name='config-prod',namespace='flux-system')
        self.graph=self.root/'cluster/graph.yaml';self.graph.write_text(yaml.safe_dump_all(objects))
    def validate(self,ref='refs/tags/v6.0.0-bootstrap.1'):

        from unittest.mock import patch
        with patch.object(v6.subprocess, 'check_output', return_value='a'*40):
            return v6.validate(self.inputs,self.config,self.root,ref,'a'*40)
    def test_valid_cold_bootstrap(self):self.assertEqual('deploy',self.validate())
    def test_destructive_operations_rejected(self):
        for op in ['destroy','migrate','deploy+migrate','deploy+init']:
            self.inputs['operation']=op
            with self.assertRaises(ValueError):self.validate()
    def test_wrong_scope_rejected(self):
        for key,value in [('cloud_provider','gcp-cloud'),('dns_mode','prod-cutover'),('cloud_account','other'),('instance_plan','4C8G')]:
            old=self.inputs[key];self.inputs[key]=value
            with self.assertRaises(ValueError):self.validate()
            self.inputs[key]=old
    def test_main_ref_is_default(self):
        self.assertEqual('deploy', self.validate('refs/tags/v6.0.0-bootstrap.1'))
    def test_missing_owner_selection_rejected(self):
        self.inputs['source_ref']=json.dumps({'gitops':'main','iac':'main'})
        with self.assertRaises(ValueError):self.validate()
    def test_flux_root_is_independent_from_node_hostname(self):
        self.assertEqual('prod-k3s-v6',self.config['node'])
        self.assertEqual('prod-k3s',self.host['host_vars']['k3s_platform_flux_root_name'])
        self.assertEqual('deploy',self.validate())
        self.host['host_vars']['k3s_platform_flux_root_name']='prod-k3s-v6'
        (self.root/'resource.yaml').write_text(yaml.safe_dump(self.decl))
        with self.assertRaisesRegex(ValueError,'Flux root'):
            self.validate()
    def test_active_release_accepted(self):
        docs=list(yaml.safe_load_all(self.graph.read_text()));docs[-1]['spec']['suspend']=False
        self.graph.write_text(yaml.safe_dump_all(docs))
        self.assertEqual('deploy', self.validate())
    def test_wrong_config_pin_rejected(self):
        docs=list(yaml.safe_load_all(self.graph.read_text()))
        next(d for d in docs if d['kind']=='GitRepository')['spec']['ref']={'branch':'main'}
        self.graph.write_text(yaml.safe_dump_all(docs))
        with self.assertRaisesRegex(ValueError,'Flux source'):self.validate()
    def test_legacy_path_excludes_v6(self):
        text=(ROOT/'.github/workflows/selfhost-orchestrator.yml').read_text()
        self.assertIn("!(github.event_name == 'workflow_dispatch' && inputs.vault_env_path == 'prod-v6')",text)
    def test_identity_roles_read_only_and_exact(self):
        import json
        for kind in ['iac','bootstrap']:
            name='github-actions-platform-ops-toolkit-prod-k3s-v6-'+kind
            role=json.loads((ROOT/'scripts/vault/roles'/f'{name}.json').read_text())
            self.assertEqual(['refs/tags/v6.*'],role['bound_claims']['ref'])
            self.assertEqual('true',role['bound_claims']['ref_protected'])
            self.assertEqual('ai-workspace-infra/Platform-Orchestrator',role['bound_claims']['repository'])
            self.assertEqual([name],role['token_policies'])
            self.assertNotIn('*',role['bound_claims']['workflow_ref'].split('@')[0])
            policy=(ROOT/'scripts/vault/policies'/f'{name}.hcl').read_text()
            self.assertNotIn('"write"',policy);self.assertNotIn('"update"',policy)

class OwnerPhaseContractTests(unittest.TestCase):
    def test_downstream_uses_frozen_owner_shas(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/selfhost-orchestrator.yml').read_text())
        job=workflow['jobs']['v6-bootstrap']
        owners={s['with']['repository']:s['with']['ref'] for s in job['steps']
                if s.get('uses','').startswith('actions/checkout')}
        for repo,key in [('playbooks','playbooks'),('iac_modules','iac')]:
            self.assertEqual('${{ needs.v6-resolve.outputs.'+key+'_sha }}',
                             owners['ai-workspace-infra/'+repo])
        config=yaml.safe_load((ROOT/'.github/config/prod-k3s-v6.yaml').read_text())
        self.assertNotIn('playbooks_sha',config)
        self.assertNotIn('iac_sha',config)
    def test_infra_runs_common_and_deploy_runs_cluster(self):
        d=yaml.safe_load((ROOT/'.github/workflows/selfhost-orchestrator.yml').read_text())['jobs']['v6-bootstrap']
        self.assertIn("inputs.operation != 'plan'", d['if'])
        owner=next(s for s in d['steps'] if s.get('uses')=='./playbooks/.github/actions/prod-k3s-bootstrap')
        self.assertEqual("${{ inputs.operation == 'infra' && 'common' || 'cluster' }}",owner['with']['phase'])
    def test_pinned_owner_supports_the_phase_contract(self):
        import os
        root=os.environ.get('V6_PLAYBOOKS_CONTRACT_ROOT')
        if not root:self.skipTest('Owner checkout checked by repository integration job')
        action=yaml.safe_load((Path(root)/'.github/actions/prod-k3s-bootstrap/action.yml').read_text())
        self.assertEqual('cluster',action['inputs']['phase']['default'])

class OwnerRefTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name)
        self.git('init','-q')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                 'commit','--allow-empty','-qm','initial')
        self.sha=self.git('rev-parse','HEAD')
        self.git('update-ref','refs/remotes/origin/main',self.sha)
        self.git('tag','v1.0.0')
    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],text=True,
                                       stderr=subprocess.DEVNULL).strip()
    def test_branch_and_annotated_tag_resolve_to_commit(self):
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                 'tag','-a','v1.0.1','-m','release')
        for ref in ('main','refs/heads/main','v1.0.0','refs/tags/v1.0.1'):
            with self.subTest(ref=ref):
                self.assertEqual(self.sha,v6.resolve_owner(self.repo,ref))
    def test_missing_and_ambiguous_refs_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'missing or ambiguous'):
            v6.resolve_owner(self.repo,'missing')
        self.git('tag','main')
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            v6.resolve_owner(self.repo,'main')
        self.assertEqual(self.sha,v6.resolve_owner(self.repo,'refs/heads/main'))
    def test_unmerged_owner_and_dirty_checkout_are_rejected(self):
        (self.repo/'untracked').touch()
        with self.assertRaisesRegex(ValueError,'Dirty'):
            v6.resolve_owner(self.repo,'main')
        self.git('add','untracked')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                 'commit','-qm','unmerged')
        self.git('update-ref','refs/remotes/origin/feature',self.git('rev-parse','HEAD'))
        with self.assertRaisesRegex(ValueError,'merged into main'):
            v6.resolve_owner(self.repo,'feature')
        with self.assertRaisesRegex(ValueError,'differs'):
            v6.resolve_owner(self.repo,'main')
    def test_structured_selection_rejects_incomplete_or_unsafe_values(self):
        for value in ('v1.0.0','{}',json.dumps({'gitops':'main','iac':'main'}),
                      json.dumps({'gitops':'main','playbooks':'feature/x','iac':'main'}),
                      json.dumps({'gitops':'main','playbooks':'main\nINJECT=yes','iac':'main'})):
            with self.subTest(value=value),self.assertRaises(ValueError):
                v6.requested_refs({'source_ref':value})


class TerminalTests(unittest.TestCase):
    def test_real_failures_cannot_be_reported_successful(self):
        spec=importlib.util.spec_from_file_location('summary', ROOT/'.github/actions/prod-k3s-summary/summary.py')
        gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
        needs={k:{'result':'success'} for k in ('v6-resolve','v6-iac','v6-bootstrap')}
        self.assertEqual(('bootstrap_owner_completed',True),gate.classify(needs,'deploy'))
        for name in needs:
            for status in ('failure','cancelled','skipped'):
                failed=copy.deepcopy(needs);failed[name]['result']=status
                self.assertFalse(gate.classify(failed,'deploy')[1])
        self.assertEqual(('verified_infrastructure_and_common',True),gate.classify(needs,'infra'))
        needs['v6-bootstrap']['result']='skipped'
        self.assertFalse(gate.classify(needs,'infra')[1])
        self.assertEqual(('verified_plan',True),gate.classify(needs,'plan'))
        self.assertFalse(gate.classify({},'deploy')[1])

if __name__=='__main__':unittest.main()
