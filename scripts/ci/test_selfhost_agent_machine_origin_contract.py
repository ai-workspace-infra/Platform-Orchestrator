#!/usr/bin/env python3
"""Regression checks for Agent Proxy machine API routing."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = [ROOT / f".github/workflows/selfhost-stage-{stage}.yml" for stage in ("deploy", "migrate", "verify")]


class SelfhostAgentMachineOriginContractTest(unittest.TestCase):
    def test_deployments_use_resolved_accounts_machine_origin(self) -> None:
        workflow = "\n".join(path.read_text() for path in WORKFLOWS)

        self.assertEqual(
            len(
                re.findall(
                    r"AGENT_CONTROLLER_URL:\s+\$\{\{ (?:needs\.provision\.outputs\.agent_accounts_base_url|fromJSON\(inputs\.provision_context \|\| .\{\}.*?\)\.outputs\.agent_accounts_base_url) \}\}",
                    workflow,
                )
            ),
            6,
        )
        self.assertIn(
            "ACCOUNTS_BASE_URL: ${{ needs.provision.outputs.agent_accounts_base_url }}",
            workflow,
        )

        # The public controller URL remains only where DNS and the release
        # summary need the customer-facing hostname.
        self.assertEqual(
            len(
                re.findall(
                    r"AGENT_CONTROLLER_URL:\s+\$\{\{ fromJSON\(needs\.stage-context\.outputs\.provision_context\)\.outputs\.agent_controller_url \}\}",
                    workflow,
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
