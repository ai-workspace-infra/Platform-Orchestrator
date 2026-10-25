"""Serverless preflight must parse top-level YAML without trusting a nested profile."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / '.github/scripts/serverless/validate_portal_runtime_domains.sh'
VALID = '''dashboardUrl: "https://console.example.test" # quoted scalar
# serverless origin
authUrl: 'https://accounts.example.test'
apiBaseUrl: https://accounts.example.test/api
'''
NESTED = '''selfhost:
  dashboardUrl: https://console-selfhost.example.test
  authUrl: https://accounts-selfhost.example.test
  apiBaseUrl: https://accounts-selfhost.example.test/api
'''


class PortalDomainYaml(unittest.TestCase):
    def check_config(self, document, environment='uat'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'src/config' / f'runtime-service-config.{environment}.yaml'
            config.parent.mkdir(parents=True)
            config.write_text(document)
            routing = root / 'routing.json'
            routing.write_text(json.dumps({'spec': {'serverless': {
                'console_host': 'console.example.test', 'accounts_host': 'accounts.example.test',
                'console_aliases': ['console-alias.example.test'], 'accounts_aliases': ['accounts-alias.example.test'],
            }}}))
            return subprocess.run(['bash', str(SCRIPT)], text=True, capture_output=True,
                                  env=dict(os.environ, PORTAL_DIR=str(root), PORTAL_ENV=environment,
                                           CLOUDFLARE_BOUNDARY_CONFIG=str(routing)))

    def test_quoted_top_level_origins_match(self):
        result = self.check_config(VALID)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nested_selfhost_fields_are_ignored_in_either_order(self):
        for document in (VALID + NESTED, NESTED + VALID):
            with self.subTest(document=document):
                result = self.check_config(document)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_top_level_mismatch_is_not_rescued_by_nested_valid_fields(self):
        for key in ('dashboardUrl', 'authUrl', 'apiBaseUrl'):
            invalid = '\n'.join(line.replace('example.test', 'wrong.test') if line.startswith(key + ':') else line
                                for line in VALID.splitlines()) + '\n'
            nested_valid = 'selfhost:\n' + '\n'.join('  '+line for line in VALID.splitlines()) + '\n'
            result = self.check_config(invalid + nested_valid)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('differs from GitOps', result.stderr)

    def test_nested_fields_cannot_replace_missing_top_level_fields(self):
        for key in ('dashboardUrl', 'authUrl', 'apiBaseUrl'):
            document = '\n'.join(line for line in VALID.splitlines() if not line.startswith(key + ':')) + '\n' + NESTED
            result = self.check_config(document)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('top-level strings', result.stderr)

    def test_invalid_types_and_empty_values_fail_closed(self):
        for value in ('null', 'true', '123', '[]', '{}', '""'):
            document = VALID.replace('https://accounts.example.test/api', value)
            result = self.check_config(document)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('top-level strings', result.stderr)

    def test_aliases_arbitrary_yaml_objects_and_non_mapping_documents_are_rejected(self):
        fixtures = ['- one\n- two\n', '--- !ruby/object:Object {}\n',
                    'origin: &origin https://console.example.test\ndashboardUrl: *origin\nauthUrl: https://accounts.example.test\napiBaseUrl: https://accounts.example.test/api\n']
        for document in fixtures:
            result = self.check_config(document)
            self.assertNotEqual(result.returncode, 0)

    def test_only_declared_aliases_are_accepted(self):
        document = VALID.replace('console.example.test', 'console-alias.example.test').replace('accounts.example.test', 'accounts-alias.example.test')
        result = self.check_config(document)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.check_config(document.replace('console-alias.example.test', 'unapproved.example.test'))
        self.assertNotEqual(result.returncode, 0)

    def test_existing_production_canonical_policy_is_preserved(self):
        result = self.check_config('production: canonical-policy-is-separate\n', environment='prod')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('skipping internal serverless host parity', result.stdout)


if __name__ == '__main__':
    unittest.main()
