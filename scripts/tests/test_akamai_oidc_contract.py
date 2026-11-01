"""Offline Akamai UAT/PROD OIDC contract test; fake Vault only."""
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

class AkamaiOIDCContract(unittest.TestCase):
    def run_bootstrap(self, target='all', mutation='', mode='--apply', helper=False, session='valid'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); binary=root/'vault';binary.write_text(FAKE);binary.chmod(0o755)
                role=json.loads((TEMPLATES/'akamai-oidc-role-uat.json.tmpl').read_text().replace('__ACCOUNT__','test-account'))
                (root/'role.json').write_text(json.dumps(role))
                # Explicit fake-only environment: do not inherit VAULT_* or provider credentials.
                env={'PATH':str(root)+os.pathsep+os.environ['PATH'],'VAULT_ADDR':'http://vault.invalid',
                     'VAULT_TOKEN':'fake-contract-only','AKAMAI_ACCOUNT_UAT':'test-uat','AKAMAI_ACCOUNT_PROD':'test-prod',
                     'FAKE_VAULT_DIR':tmp,'FAKE_MUTATION':mutation,'FAKE_SESSION':session}
                if os.environ.get('GITOPS_ROOT'):
                    env['GITOPS_ROOT']=os.environ['GITOPS_ROOT']
                if helper: env.pop('VAULT_TOKEN')
                result=subprocess.run(['bash',str(SCRIPT),mode,'--env',target],env=env,text=True,capture_output=True)
                calls=[json.loads(x) for x in (root/'calls').read_text().splitlines()] if (root/'calls').exists() else []
                files={p.name:p.read_text() for p in root.glob('*.hcl')}
                written=json.loads((root/'role.json').read_text())
                return result,calls,files,written

    def test_all_preserves_existing_uat_prod_set(self):
            result,calls,files,_=self.run_bootstrap(target='all')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(len(files),2)
            self.assertTrue(any('-uat-' in x for x in files));self.assertTrue(any('-prod-' in x for x in files))
            self.assertFalse(any('-dev-' in x for x in files))
            self.assertFalse(any(x[0]=='token' for x in calls))


if __name__ == '__main__': unittest.main()
