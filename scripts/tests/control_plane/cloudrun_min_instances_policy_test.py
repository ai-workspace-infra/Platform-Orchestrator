"""Verify the deployment owner pins Cloud Run min instances to zero everywhere."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SCRIPT = ROOT / "scripts/serverless_uat/deploy_cloudrun_services.sh"


class CloudRunMinInstancesPolicyTests(unittest.TestCase):
    def test_uat_and_prod_ignore_overrides_and_scale_to_zero(self):
        for environment in ("uat", "prod"):
            with self.subTest(environment=environment), tempfile.TemporaryDirectory() as temp_dir:
                temp = Path(temp_dir)
                bin_dir = temp / "bin"
                bin_dir.mkdir()
                args_file = temp / "gcloud-args"
                gcloud = bin_dir / "gcloud"
                gcloud.write_text(
                    "#!/usr/bin/env bash\n"
                    "printf '%s\\n' \"$@\" >> \"$GCLOUD_ARGS_FILE\"\n"
                )
                gcloud.chmod(0o755)

                env = dict(os.environ)
                env.update(
                    {
                        "PATH": f"{bin_dir}:{env['PATH']}",
                        "GCLOUD_ARGS_FILE": str(args_file),
                        "GCP_PROJECT_ID": "offline-test-project",
                        "GCP_REGION": "asia-northeast1",
                        "SUPABASE_CONNECT_URI": "postgresql://offline-test",
                        "INTERNAL_SERVICE_TOKEN": "offline-test-token",
                        "DEPLOY_ENV": environment,
                        "CLOUD_RUN_SERVICE": "billing-service",
                        "CLOUD_RUN_MIN_INSTANCES": "4",
                    }
                )
                result = subprocess.run(
                    ["bash", str(DEPLOY_SCRIPT)],
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                args = args_file.read_text().splitlines()
                self.assertIn("--min-instances=0", args)
                self.assertNotIn("--min-instances=4", args)


if __name__ == "__main__":
    unittest.main()
