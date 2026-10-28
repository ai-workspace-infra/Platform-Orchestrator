#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('main_event', ROOT / '.github/scripts/feature-lane/main-event.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MainEventTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        tag = 'smoke-sit-test-1483'
        path = Path(temp.name) / '.github/feature-candidates' / tag / 'candidate.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'feature_tag': tag}))
        self.env = {'GITHUB_REPOSITORY': 'ai-workspace-infra/Platform-Orchestrator',
                    'GITHUB_EVENT_NAME': 'workflow_run', 'GITHUB_REF': 'refs/heads/main',
                    'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKSPACE': temp.name}
        self.event = {'action': 'completed', 'workflow_run': {'id': 123, 'run_attempt': 1}}
        self.run = {'id': 123, 'run_attempt': 1, 'workflow_id': 456,
                    'path': '.github/workflows/feature-tag-preflight.yml@refs/tags/' + tag,
                    'event': 'push', 'status': 'completed', 'head_branch': tag, 'head_sha': 'b' * 40,
                    'repository': {'full_name': self.env['GITHUB_REPOSITORY']},
                    'head_repository': {'full_name': self.env['GITHUB_REPOSITORY']}}
        self.trusted = Mock()
        def api(path):
            if '/actions/workflows/' in path:
                return {'id': 456}
            if '/contents/' in path:
                return {'type': 'file', 'path': '.github/workflows/feature-tag-preflight.yml', 'sha': 'd' * 40}
            return self.run
        self.trusted.reader.api.side_effect = api
        self.trusted.policy_at.return_value = {}
        self.trusted.verify_feature_tag.return_value = {'repository': self.env['GITHUB_REPOSITORY'], 'target_sha': 'b' * 40}

    def test_main_event_validates_exact_run_and_reviewed_tag(self):
        self.assertEqual(module.authenticate(self.event, self.env, self.trusted), 'smoke-sit-test-1483')
        self.trusted.policy_at.assert_called_once_with('a' * 40)
        self.trusted.verify_feature_tag.assert_called_once()

    def test_rejects_untrusted_ref_run_or_moved_tag(self):
        for key, value in [('event', 'pull_request'), ('workflow_id', 999), ('run_attempt', 2),
                           ('head_sha', 'c' * 40), ('head_branch', 'other'), ('status', 'in_progress')]:
            with self.subTest(key=key):
                original = self.run[key]
                self.run[key] = value
                with self.assertRaises(ValueError):
                    module.authenticate(self.event, self.env, self.trusted)
                self.run[key] = original
        with self.assertRaises(ValueError):
            module.authenticate(self.event, dict(self.env, GITHUB_REF='refs/tags/unsafe'), self.trusted)
        self.trusted.verify_feature_tag.return_value['repository'] = 'foreign/repo'
        with self.assertRaises(ValueError):
            module.authenticate(self.event, self.env, self.trusted)

    def test_rejects_changed_source_workflow(self):
        original = self.trusted.reader.api.side_effect
        def api(path):
            result = original(path)
            if '/contents/' in path and path.endswith('b' * 40):
                return dict(result, sha='c' * 40)
            return result
        self.trusted.reader.api.side_effect = api
        with self.assertRaisesRegex(ValueError, 'workflow differs'):
            module.authenticate(self.event, self.env, self.trusted)


if __name__ == '__main__':
    unittest.main()
