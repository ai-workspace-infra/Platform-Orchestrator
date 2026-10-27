"""Exercise bootstrap with a fake Vault binary; never contact Vault or load credentials."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/cloud/bootstrap/Akamai-Cloud/bootstrap_akamai_oidc_roles.sh'
TEMPLATES = ROOT / 'scripts/vault/templates'
FAKE = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
root=pathlib.Path(os.environ['FAKE_VAULT_DIR'])
a=sys.argv[1:]
with (root/'calls').open('a') as f: f.write(json.dumps(a)+'\n')
if a[:2] == ['token','lookup']:
 session=os.environ.get('FAKE_SESSION','valid')
 if session=='invalid': sys.exit(2)
 print(json.dumps({'data':{'id':'DO-NOT-EXPOSE-FAKE-TOKEN','policies':['root'] if session=='root' else ['dev-policy-manager'],'ttl':0 if session=='expired' else 1200}}))
elif a[:2] == ['token','capabilities']:
 print(json.dumps(['read'] if os.environ.get('FAKE_SESSION')=='insufficient' else ['read','create','update']))
elif a[:2] == ['policy','write']:
 (root/(a[2]+'.hcl')).write_text(pathlib.Path(a[3]).read_text())
elif a[0] == 'write':
 (root/'role.json').write_text(sys.stdin.read())
elif a[0] == 'read' and '-format=json' in a:
 role=json.loads((root/'role.json').read_text())
 mutation=os.environ.get('FAKE_MUTATION','')
 if mutation=='glob': role['bound_claims_type']='glob'
 elif mutation=='wildcard': role['bound_claims']['job_workflow_ref']='*'
 elif mutation=='wrong-environment': role['bound_claims']['environment']='uat'
 elif mutation=='wrong-repository': role['bound_claims']['repository']='other/repo'
 elif mutation=='wrong-ref': role['bound_claims']['ref']='refs/heads/feature'
 elif mutation=='wrong-caller': role['bound_claims']['workflow_ref']='ai-workspace-infra/platform-ops-toolkit/.github/workflows/iac-orchestrator.yml@refs/heads/main'
 elif mutation=='extra-workflow': role['bound_claims']['job_workflow_ref']=[role['bound_claims']['job_workflow_ref'],'*']
 elif mutation=='extra-policy': role['token_policies'].append('root')
 elif mutation=='default-policy': role['token_no_default_policy']=False
 elif mutation=='wrong-audience': role['bound_audiences']=['other']
 print(json.dumps({'data':role}))
'''

class DevOIDCContract(unittest.TestCase):
    def run_bootstrap(self, target='dev', mutation='', mode='--apply', helper=False, session='valid'):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); binary=root/'vault';binary.write_text(FAKE);binary.chmod(0o755)
            role=json.loads((TEMPLATES/'akamai-oidc-role-dev.json.tmpl').read_text().replace('__ACCOUNT__','test-account'))
            (root/'role.json').write_text(json.dumps(role))
            # Explicit fake-only environment: do not inherit VAULT_* or provider credentials.
            env={'PATH':str(root)+os.pathsep+os.environ['PATH'],'VAULT_ADDR':'http://vault.invalid',
                 'VAULT_TOKEN':'fake-contract-only','AKAMAI_ACCOUNT_DEV':'test-account',
                 'AKAMAI_ACCOUNT_UAT':'test-uat','AKAMAI_ACCOUNT_PROD':'test-prod',
                 'FAKE_VAULT_DIR':tmp,'FAKE_MUTATION':mutation,'FAKE_SESSION':session}
            if helper: env.pop('VAULT_TOKEN')
            result=subprocess.run(['bash',str(SCRIPT),mode,'--env',target],env=env,text=True,capture_output=True)
            calls=[json.loads(x) for x in (root/'calls').read_text().splitlines()] if (root/'calls').exists() else []
            files={p.name:p.read_text() for p in root.glob('*.hcl')}
            written=json.loads((root/'role.json').read_text())
            return result,calls,files,written

    def test_dev_complete_exact_contract_and_read_only_policy(self):
        result,calls,files,role=self.run_bootstrap()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(role['bound_claims_type'],'string')
        self.assertEqual(role['bound_claims']['environment'],'dev')
        self.assertEqual(role['bound_claims']['ref'],'refs/heads/main')
        self.assertEqual(role['bound_claims']['repository'],'ai-workspace-infra/platform-ops-toolkit')
        self.assertEqual(role['bound_claims']['workflow_ref'],'ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-host-lifecycle.yml@refs/heads/main')
        self.assertEqual(role['bound_claims']['job_workflow_ref'],'ai-workspace-infra/platform-ops-toolkit/.github/workflows/iac-pipeline-multi-cloud-stages.yaml@refs/heads/main')
        self.assertEqual(role['bound_audiences'],['vault'])
        self.assertEqual(role['role_type'],'jwt');self.assertEqual(role['user_claim'],'sub')
        self.assertTrue(role['token_no_default_policy']);self.assertEqual(role['token_type'],'batch')
        self.assertEqual(role['token_ttl'],'20m');self.assertEqual(role['token_max_ttl'],'20m')
        self.assertEqual(role['token_policies'],['github-actions-platform-ops-toolkit-dev-akamai-oidc-bootstrap-test-account'])
        policy=next(iter(files.values()))
        self.assertEqual(policy,(TEMPLATES/'akamai-oidc-policy.hcl.tmpl').read_text().replace('__ENV__','dev').replace('__ACCOUNT__','test-account'))
        self.assertEqual(policy.count('capabilities = ["read"]'),4)
        self.assertNotIn('kv/data/CICD/uat',policy);self.assertNotIn('kv/data/CICD/prod',policy)
        self.assertTrue(any(x[:1]==['write'] for x in calls))

    def test_wrong_or_broad_dev_roles_are_rejected_in_check_mode(self):
        for mutation in ('glob','wildcard','wrong-environment','wrong-repository','wrong-ref','wrong-caller','extra-workflow','extra-policy','default-policy','wrong-audience'):
            with self.subTest(mutation=mutation):
                result,calls,_,_=self.run_bootstrap(mutation=mutation,mode='--check')
                self.assertNotEqual(result.returncode,0)
                self.assertIn('Dev Akamai role claims',result.stderr)
                self.assertFalse(any(x[0]=='write' or x[:2]==['policy','write'] for x in calls))

    def test_managed_bootstrap_role_keeps_bootstrap_adds_exact_dev_feature_and_two_read_paths(self):
        name='github-actions-playbooks-dev-k3s-bootstrap'
        declared=json.loads((ROOT/'scripts/vault/roles'/f'{name}.json').read_text())
        self.assertEqual(declared['bound_claims_type'],'string')
        self.assertEqual(declared['bound_claims'],{
            'repository':'ai-workspace-infra/platform-ops-toolkit',
            'ref':'refs/heads/main','environment':'dev',
            'workflow_ref':['ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-host-lifecycle.yml@refs/heads/main','ai-workspace-infra/platform-ops-toolkit/.github/workflows/dev-feature-deploy.yml@refs/heads/main'],
            'job_workflow_ref':['ai-workspace-infra/playbooks/.github/workflows/dev-k3s-bootstrap.yml@e4607530b545ccf09e4045113afeb644b067823e','ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@41c00edbf14c77fe164df18e2a87c48244387901','ai-workspace-infra/playbooks/.github/workflows/dev-feature-flux.yml@298235179326d05f085923fc561cfcbc66c0d05f','ai-workspace-infra/playbooks/.github/workflows/dev-web-saas-seed.yml@6949b3f202114a135ab8db0e645286bb44bbdc64','ai-workspace-infra/playbooks/.github/workflows/dev-platform-ingress.yml@41c00edbf14c77fe164df18e2a87c48244387901']})
        self.assertEqual(declared['token_policies'],[name])
        self.assertTrue(declared['token_no_default_policy'])
        self.assertEqual(declared['token_type'],'batch')
        self.assertEqual(declared['token_ttl'],'20m');self.assertEqual(declared['token_max_ttl'],'20m')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'vault';binary.write_text(FAKE);binary.chmod(0o755)
            env={'PATH':str(root)+os.pathsep+os.environ['PATH'],'VAULT_ADDR':'http://vault.invalid',
                 'VAULT_TOKEN':'fake-contract-only','FAKE_VAULT_DIR':tmp}
            result=subprocess.run(['bash',str(ROOT/'scripts/create_vault_service_repo_roles.sh'),'--apply','--role',name],env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            role=json.loads((root/'role.json').read_text())
            self.assertEqual(role,{k:v for k,v in declared.items() if k not in ('role_name','description')})
            self.assertEqual(list(root.glob('*.hcl')),[root/f'{name}.hcl'])
            self.assertEqual((root/f'{name}.hcl').read_text(),'path "kv/data/CICD/dev/k3s-bootstrap" {\n  capabilities = ["read"]\n}\n\npath "kv/data/CICD/dev/ghcr" {\n  capabilities = ["read"]\n}\n')
            calls=[json.loads(x) for x in (root/'calls').read_text().splitlines()]
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[0][:3],['policy','write',name])
            self.assertEqual(calls[1],['write','auth/jwt/role/'+name,'-'])

    def test_dev_uses_helper_without_copying_token(self):
        result,calls,_,_=self.run_bootstrap(helper=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(['token','lookup','-format=json'],calls)
        self.assertNotIn('DO-NOT-EXPOSE',result.stdout+result.stderr)

    def test_root_invalid_expired_or_insufficient_helper_never_reads_or_writes_roles(self):
        for session in ('root','invalid','expired','insufficient'):
            with self.subTest(session=session):
                result,calls,files,_=self.run_bootstrap(helper=True,session=session)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(files)
                self.assertTrue(all(x[0]=='token' for x in calls),calls)
                self.assertNotIn('DO-NOT-EXPOSE',result.stdout+result.stderr)

    def test_all_preserves_existing_uat_prod_set(self):
        result,calls,files,_=self.run_bootstrap(target='all')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(files),2)
        self.assertTrue(any('-uat-' in x for x in files));self.assertTrue(any('-prod-' in x for x in files))
        self.assertFalse(any('-dev-' in x for x in files))
        self.assertFalse(any(x[0]=='token' for x in calls))

if __name__=='__main__': unittest.main()
