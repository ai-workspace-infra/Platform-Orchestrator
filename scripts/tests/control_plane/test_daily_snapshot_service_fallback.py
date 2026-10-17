"""Offline regression for suppressed push events and rejected build dispatches."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
TAG = "daily-build-2026.10.16"
SHA = "a" * 40
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
marker = Path(os.environ['DISPATCH_MARKER'])
if a[:2] == ['auth', 'status']: pass
elif a[0] == 'api':
    endpoint = a[1]
    if '/commits/' in endpoint: print('a' * 40)
    elif '/git/ref/' in endpoint: print(json.dumps({'object': {'sha': 'a' * 40}}))
    elif '/releases/tags/' in endpoint: print('123')
    elif '/assets?' in endpoint: print('["release-manifest.json"]')
    else: print('main')
elif a[:2] == ['workflow', 'run']:
    if os.environ['SCENARIO'] == 'disabled':
        print('Actions has been disabled for this repository', file=sys.stderr)
        sys.exit(1)
    marker.write_text('dispatched')
elif a[:2] == ['run', 'list']:
    scenario = os.environ['SCENARIO']
    runs = []
    if scenario == 'existing' or marker.exists():
        runs = [{'databaseId': 123, 'event': 'workflow_dispatch' if marker.exists() else 'push',
                 'headBranch': os.environ['SNAPSHOT_TAG'], 'headSha': 'a' * 40}]
    else:
        # Wrong-SHA runs must not suppress the exact-snapshot fallback.
        runs = [{'databaseId': 99, 'event': 'push', 'headBranch': os.environ['SNAPSHOT_TAG'], 'headSha': 'b' * 40}]
    print(json.dumps(runs))
elif a[:2] == ['run', 'view']: print('{"status":"completed","conclusion":"success"}')
elif a[:2] == ['release', 'view']: print('https://example.invalid/release')
else: sys.exit('unexpected gh invocation: ' + repr(a))
'''


class ServiceFallbackTest(unittest.TestCase):
    def run_snapshot(self, repo, scenario):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'gh').write_text(FAKE_GH)
            (root / 'gh').chmod(0o755)
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'GH_TOKEN': 'offline-test', 'DEPLOY_ENV': 'uat', 'SNAPSHOT_TAG': TAG,
                   'SNAPSHOT_ORGS': 'ai-workspace-services', 'SNAPSHOT_REPOS': repo,
                   'GITHUB_WORKSPACE': str(ROOT), 'SNAPSHOT_STATUS_FILE': str(root / 'status'),
                   'BUILD_DISCOVERY_GRACE_SECONDS': '0', 'BUILD_TIMEOUT_SECONDS': '5',
                   'BUILD_POLL_SECONDS': '0', 'DISPATCH_MARKER': str(root / 'dispatched'),
                   'SCENARIO': scenario}
            result = subprocess.run(['bash', str(ROOT / '.github/scripts/snapshots/tag-daily-main-snapshot.sh')],
                                    env=env, text=True, capture_output=True, timeout=15)
            statuses = [json.loads(line) for line in (root / 'status').read_text().splitlines()]
            return result, statuses, (root / 'dispatched').exists()

    def test_missing_push_dispatches_exact_tag_for_each_service(self):
        for name in ('accounts', 'postgresql', 'portal'):
            with self.subTest(name=name):
                result, statuses, dispatched = self.run_snapshot('ai-workspace-services/' + name, 'missing')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(dispatched)
                self.assertEqual(statuses[-1]['status'], 'build_succeeded')
                self.assertEqual(statuses[-1]['sha'], SHA)

    def test_existing_push_is_reused_without_duplicate_dispatch(self):
        result, statuses, dispatched = self.run_snapshot('ai-workspace-services/accounts', 'existing')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(dispatched)
        self.assertEqual(statuses[-1]['status'], 'build_succeeded')

    def test_disabled_actions_fails_before_waiting(self):
        result, statuses, dispatched = self.run_snapshot('ai-workspace-services/postgresql', 'disabled')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(dispatched)
        self.assertEqual(statuses[-1]['status'], 'build_failed')
        self.assertIn('dispatch rejected', statuses[-1]['detail'])


if __name__ == '__main__':
    unittest.main()
