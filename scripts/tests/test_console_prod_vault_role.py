import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ConsoleProdVaultRoleTests(unittest.TestCase):
    def test_portal_prod_v2_tags_are_allowed_with_only_shared_cicd_scope(self):
        role = json.loads(
            (ROOT / "scripts/vault/roles/github-actions-console-prod.json").read_text()
        )
        claims = role["bound_claims"]

        self.assertEqual(claims["repository"], "ai-workspace-services/portal")
        self.assertEqual(
            claims["job_workflow_ref"],
            "ai-workspace-services/portal/.github/workflows/*pipeline.ym*@*",
        )
        self.assertEqual(
            set(claims["ref"]),
            {
                "refs/tags/v*",
                "refs/tags/prod-v2-*",
                "refs/heads/release/v*",
            },
        )
        self.assertEqual(role["token_policies"], ["github-actions-console"])


if __name__ == "__main__":
    unittest.main()
