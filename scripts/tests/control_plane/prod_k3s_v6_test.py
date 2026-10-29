import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('v6',ROOT/'.github/scripts/platform-ops/provision/resolve-prod-k3s-v6.py')
v6=importlib.util.module_from_spec(spec);spec.loader.exec_module(v6)

class RequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config={'iac_sha':'a'*40,'playbooks_sha':'b'*40,'resource_manifest':'resource.yaml','target_manifest':'target.yaml','root_path':'cluster','node':'prod-k3s-v6'}
        self.inputs={'vault_env_path':'prod-v6','cloud_provider':'akamai-cloud','cloud_account':'manbuzhe2026','instance_plan':'2C4G','target_domains':'web-saas','dns_mode':'none','open_platform_service':'none','offline_mode':'off','runner_type':'ubuntu-latest','operation':'deploy','include_external_agent_proxy':False,'skip_stripe_catalog':True,'source_ref':'v1.0.0'}
        self.host={'name':'prod-k3s-v6','type':'g6-standard-2','region':'jp-tyo-3','image':'linode/debian13','volume':{'label':'prod-k3s-v6-data','size':100,'filesystem':'ext4'},'firewall':{'ssh_cidrs':['0.0.0.0/0'],'ssh_ipv6_cidrs':[],'additional_tcp_ports':[]},'host_vars':{'public_dns_cutover':False,'reserved_dns_aliases':{},'target_generation':'prod-v6','k3s_platform_flux_bootstrap_mode':'declarative_paused','k3s_platform_flux_root_name':'prod-k3s-v6','k3s_platform_write_kubeconfig_mode':'0600','k3s_platform_local_storage_path':'/data/k3s/storage','k3s_platform_require_data_mount':True}}
        decl={'global':{'provider':'akamai-cloud','environment':'prod','account':'manbuzhe2026','workspace':'prod-k3s-v6','state_namespace':'prod-k3s-v6','prevent_destroy':True},'hosts':[self.host]}
        (self.root/'resource.yaml').write_text(yaml.safe_dump(decl))
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
        self.graph=self.root/'cluster/graph.yaml';self.graph.write_text(yaml.safe_dump_all(objects))
    def validate(self,ref='refs/tags/v6.0.0-bootstrap.1'):
        return v6.validate(self.inputs,self.config,self.root,ref)
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
    def test_main_ref_rejected(self):
        with self.assertRaises(ValueError):self.validate('refs/heads/main')
    def test_missing_owner_pin_rejected(self):
        self.config['playbooks_sha']='main'
        with self.assertRaises(ValueError):self.validate()
    def test_active_release_rejected(self):
        docs=list(yaml.safe_load_all(self.graph.read_text()));docs[-1]['spec']['suspend']=False
        self.graph.write_text(yaml.safe_dump_all(docs))
        with self.assertRaisesRegex(ValueError,'paused'):self.validate()
    def test_wrong_config_pin_rejected(self):
        self.inputs['source_ref']='v2.0.0'
        with self.assertRaisesRegex(ValueError,'reviewed tag'):self.validate()
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

class TerminalTests(unittest.TestCase):
    def test_real_failures_cannot_be_reported_successful(self):
        spec=importlib.util.spec_from_file_location('summary', ROOT/'.github/actions/prod-k3s-summary/summary.py')
        gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
        needs={k:{'result':'success'} for k in ('v6-resolve','v6-iac','v6-bootstrap')}
        self.assertEqual(('verified_paused_bootstrap',True),gate.classify(needs,'deploy'))
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
