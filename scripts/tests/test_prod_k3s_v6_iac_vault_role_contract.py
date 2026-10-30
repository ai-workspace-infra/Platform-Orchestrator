import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
ROLE_NAME = "github-actions-platform-ops-toolkit-prod-k3s-v6-iac"


class ProdK3sV6IacVaultRoleContract(unittest.TestCase):
    def test_role_is_provisionable_and_bound_to_protected_main_workflows(self):
        role = json.loads(
            (ROOT / "scripts/vault/roles" / f"{ROLE_NAME}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(role["role_name"], ROLE_NAME)
        self.assertTrue(role["description"])
        self.assertEqual(role["role_type"], "jwt")
        self.assertEqual(role["token_type"], "batch")
        self.assertTrue(role["token_no_default_policy"])
        self.assertEqual(role["token_ttl"], "20m")
        self.assertEqual(role["token_max_ttl"], "20m")
        self.assertEqual(role["token_explicit_max_ttl"], "20m")
        claims = role["bound_claims"]
        self.assertEqual(claims["repository"], "ai-workspace-infra/Platform-Orchestrator")
        self.assertEqual(claims["environment"], "prod")
        self.assertEqual(claims["ref"], ["refs/heads/main"])
        self.assertEqual(claims["ref_protected"], "true")
        self.assertEqual(
            claims["workflow_ref"],
            "ai-workspace-infra/Platform-Orchestrator/.github/workflows/iac-orchestrator.yml@refs/heads/main",
        )
        self.assertEqual(
            claims["job_workflow_ref"],
            "ai-workspace-infra/Platform-Orchestrator/.github/workflows/iac-pipeline-multi-cloud-stages.yaml@refs/heads/main",
        )
        self.assertEqual(role["token_policies"], [ROLE_NAME])

    def test_policy_is_read_only_and_limited_to_iac_state(self):
        policy = (ROOT / "scripts/vault/policies" / f"{ROLE_NAME}.hcl").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            policy.strip(),
            'path "kv/data/CICD/prod/akamai-cloud/manbuzhe2026" {\n'
            '  capabilities = ["read"]\n}\n'
            'path "kv/data/CICD/prod/iac_state" {\n'
            '  capabilities = ["read"]\n}',
        )


if __name__ == "__main__":
    unittest.main()
