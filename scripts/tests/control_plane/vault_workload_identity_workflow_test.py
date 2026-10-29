import unittest
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[3]

class Workflow(unittest.TestCase):
    def setUp(self):
        self.w=yaml.safe_load((ROOT/'.github/workflows/vault-workload-identity.yml').read_text())
        self.steps=self.w['jobs']['identity']['steps']
    def test_reviewed_inputs_and_protected_ref(self):
        trigger=self.w.get('on',self.w.get(True))['workflow_dispatch']['inputs']
        self.assertEqual(set(trigger),{'mode','gitops_tag','operation_path','environment','playbooks_sha'})
        self.assertEqual(self.w['jobs']['identity']['needs'],'validate')
        self.assertEqual(self.w['jobs']['identity']['environment'],'${{ inputs.environment }}')
        guard=self.w['jobs']['validate']['steps'][0]['run']
        self.assertIn('"$REF_PROTECTED" == true',guard)
    def test_evidence_and_owner_are_connected(self):
        names=[x.get('name','') for x in self.steps]
        self.assertLess(names.index('Verify declared operation and evidence'),names.index('Acquire host access identity'))
        self.assertLess(names.index('Verify current provider host key'),names.index('Execute the reviewed identity owner'))
        action=next(x for x in self.steps if x.get('uses')=='./playbooks/.github/actions/workload-identity-operation')
        self.assertEqual(action['with']['operation-path'],'${{ inputs.operation_path }}')
        self.assertEqual(action['with']['bootstrap-receipt'],'${{ steps.evidence.outputs.directory }}/bootstrap.json')
        admin=next(x for x in self.steps if x.get('id')=='admin')
        self.assertEqual(admin['if'],"${{ inputs.mode == 'configure' }}")
        self.assertEqual(admin['with']['role'],'${{ steps.evidence.outputs.admin_role }}')
        self.assertTrue(admin['with']['outputToken'])
    def test_provider_guard_and_no_host_mutations_in_pipeline(self):
        guard=next(x for x in self.steps if x.get('name')=='Verify environment and provider')['run']
        self.assertIn('"$DECLARED_ENVIRONMENT" == "$REQUESTED_ENVIRONMENT"',guard)
        self.assertIn('"$DECLARED_PROVIDER" == akamai-cloud',guard)
        scripts='\n'.join(x.get('run','') for x in self.steps)
        for word in ('kubectl ','ssh ','terraform ','flux '):self.assertNotIn(word,scripts)

if __name__=='__main__':unittest.main()
