"""The probe must not claim success for missing access or missing denials."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('probe', ROOT / '.github/scripts/feature-lane/vault-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://example.invalid/token',
                                          'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'test'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.oidc = (200, json.dumps({'value': 'jwt'}).encode())
        self.login = (200, json.dumps({'auth': {'client_token': 'token'}}).encode())

    def test_allowed_requires_both_expected_path_results(self):
        with patch.object(probe, 'request', side_effect=[self.oidc, self.login, (200, b''), (403, b'')]):
            probe.main('allowed')
        for allowed, denied in [(403, 403), (200, 200), (200, 404)]:
            with self.subTest(allowed=allowed, denied=denied), patch.object(probe, 'request', side_effect=[self.oidc, self.login, (allowed, b''), (denied, b'')]):
                with self.assertRaises(ValueError):
                    probe.main('allowed')

    def test_missing_environment_requires_login_denial(self):
        for mode in ('denied-environment', 'denied-caller', 'deploy-denied'):
            with self.subTest(mode=mode), patch.object(probe, 'request', side_effect=[self.oidc, (400, b'')]):
                probe.main(mode)
        with patch.object(probe, 'request', side_effect=[self.oidc, self.login]):
            with self.assertRaises(ValueError):
                probe.main('denied-environment')

    def test_deploy_probe_uses_only_deploy_role(self):
        with patch.object(probe, 'request', side_effect=[self.oidc, self.login, (200, b''), (403, b'')]) as request:
            probe.main('deploy-allowed')
        self.assertEqual(json.loads(request.call_args_list[1].kwargs['body'])['role'],
                         'github-actions-feature-lane-deploy-evidence-read-sit')

if __name__ == '__main__':
    unittest.main()
