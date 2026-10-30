import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]


class ProductionReleaseTagPolicyContract(unittest.TestCase):
    def test_production_release_protection_accepts_generic_v_tags(self):
        policy = json.loads(
            (ROOT / ".github/policies/prod-immutable-release-tags.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(policy["target"], "tag")
        self.assertEqual(policy["enforcement"], "active")
        self.assertEqual(
            policy["conditions"]["ref_name"]["include"], ["refs/tags/v*"]
        )
        self.assertEqual(
            {rule["type"] for rule in policy["rules"]}, {"update", "deletion"}
        )


if __name__ == "__main__":
    unittest.main()
