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
if a[:2] == ['policy','write']:
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
    def run_bootstrap(self, target='dev', mutation='', mode='--apply'):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); binary=root/'vault';binary.write_text(FAKE);binary.chmod(0o755)
            role=json.loads((TEMPLATES/'akamai-oidc-role-dev.json.tmpl').read_text().replace('__ACCOUNT__','test-account'))
            (root/'role.json').write_text(json.dumps(role))
            # Explicit fake-only environment: do not inherit VAULT_* or provider credentials.
            env={'PATH':str(root)+os.pathsep+os.environ['PATH'],'VAULT_ADDR':'http://vault.invalid',
                 'VAULT_TOKEN':'fake-contract-only','AKAMAI_ACCOUNT_DEV':'test-account',
                 'AKAMAI_ACCOUNT_UAT':'test-uat','AKAMAI_ACCOUNT_PROD':'test-prod',
                 'FAKE_VAULT_DIR':tmp,'FAKE_MUTATION':mutation}
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

    def test_all_preserves_existing_uat_prod_set(self):
        result,calls,files,_=self.run_bootstrap(target='all')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(files),2)
        self.assertTrue(any('-uat-' in x for x in files));self.assertTrue(any('-prod-' in x for x in files))
        self.assertFalse(any('-dev-' in x for x in files))

if __name__=='__main__': unittest.main()
