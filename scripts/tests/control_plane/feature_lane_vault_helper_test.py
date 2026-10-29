"""Validate secret-safe environment helper behavior with fake providers."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('feature_tokens', ROOT / 'scripts/vault/validate-feature-lane-tokens.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

class ValidatorTest(unittest.TestCase):
    def test_requires_exact_read_scopes(self):
        def good(url, token):
            return ({'login':'example'}, {'X-OAuth-Scopes':'read:packages'}) if 'github.com' in url else ({'scopes':'linodes:read_only'}, {})
        with patch.object(validator, 'profile', side_effect=good):
            validator.main({'GHCR_USERNAME':'example','GHCR_TOKEN':'synthetic','LINODES_TOKEN':'synthetic'})
        for scopes in ('read:packages, repo', ''):
            with self.subTest(scopes=scopes), patch.object(validator, 'profile', return_value=({'login':'example'}, {'X-OAuth-Scopes':scopes})), self.assertRaises(ValueError):
                validator.main({'GHCR_USERNAME':'example','GHCR_TOKEN':'synthetic'})
        with patch.object(validator, 'profile') as request:
            validator.main({'LINODES_TOKEN':'synthetic'})
            request.assert_not_called()

class HelperTest(unittest.TestCase):
    def test_existing_paths_use_patch_and_preserve_other_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);log=root/'calls';vault=root/'vault'
            vault.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_LOG"\nexit 0\n');vault.chmod(0o700)
            python=root/'python3';python.write_text('#!/bin/sh\nexit 0\n');python.chmod(0o700)
            env={**os.environ,'PATH':str(root)+':'+os.environ['PATH'],'FAKE_LOG':str(log),
                 'GHCR_USERNAME':'example','GHCR_TOKEN':'synthetic-secret','LINODES_TOKEN':'',
                 'CLOUDFLARE_ACCOUNT_ID':'','CLOUDFLARE_DNS_TOKEN':''}
            result=subprocess.run(['bash',str(ROOT/'scripts/vault/update-feature-lane-vault.sh')],env=env,text=True,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            calls=log.read_text();self.assertEqual(calls.count('kv patch '),2);self.assertNotIn('kv put ',calls)
            self.assertNotIn('synthetic-secret',calls+result.stdout+result.stderr)

    def test_one_readonly_ghcr_identity_populates_two_paths_without_printing_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); log=root/'calls'
            vault=root/'vault'
            vault.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_LOG"\nif [ "$1" = token ]; then exit 0; fi\nif [ "$1" = kv ] && [ "$2" = metadata ]; then exit 2; fi\nexit 0\n')
            vault.chmod(0o700)
            python=root/'python3';python.write_text('#!/bin/sh\nexit 0\n');python.chmod(0o700)
            env={**os.environ,'PATH':str(root)+':'+os.environ['PATH'],'FAKE_LOG':str(log),
                 'GHCR_USERNAME':'example','GHCR_TOKEN':'synthetic-secret','LINODES_TOKEN':'synthetic-linode',
                 'CLOUDFLARE_ACCOUNT_ID':'','CLOUDFLARE_DNS_TOKEN':''}
            result=subprocess.run(['bash',str(ROOT/'scripts/vault/update-feature-lane-vault.sh')],env=env,text=True,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            calls=log.read_text()
            self.assertIn('kv/sit/platform/ghcr/feature-baseline',calls)
            self.assertIn('kv/sit/platform/ghcr/feature-registry',calls)
            self.assertIn('kv/sit/platform/akamai/feature-target',calls)
            self.assertEqual(calls.count('-cas=0'),3)
            self.assertNotIn('synthetic-secret',calls+result.stdout+result.stderr)
            self.assertNotIn('synthetic-linode',calls+result.stdout+result.stderr)

if __name__=='__main__': unittest.main()
