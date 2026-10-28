#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import yaml

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
        path.write_text(json.dumps({'feature_tag': tag,
                                   'task_url': 'https://github.com/ai-workspace-infra/Platform-Orchestrator/issues/1483',
                                   'sources': [{'repository': 'ai-workspace-services/accounts'}],
                                   'gitops': {'repository': 'ai-workspace-infra/gitops'}, 'configurations': []}))
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
        self.trusted.policy_at.return_value = {'gitops_repository': 'ai-workspace-infra/gitops',
            'website_content_canonical_repository': 'ai-workspace-services/knowledge',
            'task_repositories': ['ai-workspace-infra/Platform-Orchestrator']}
        self.trusted.verify_feature_tag.return_value = {'repository': self.env['GITHUB_REPOSITORY'], 'target_sha': 'b' * 40}

    def test_main_event_validates_exact_run_and_reviewed_tag(self):
        tag, repos = module.authenticate(self.event, self.env, self.trusted)
        self.assertEqual(tag, 'smoke-sit-test-1483')
        self.assertEqual(repos['ai-workspace-services'], ['accounts', 'knowledge'])
        self.assertEqual(repos['ai-workspace-infra'], ['gitops', 'Platform-Orchestrator'])
        self.trusted.policy_at.assert_called_once_with('a' * 40)
        self.trusted.verify_feature_tag.assert_called_once()
        self.trusted.gate.validate_candidate.assert_called_once()

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

    def test_rejects_repository_outside_two_approved_installations(self):
        candidate = {'task_url': 'https://github.com/ai-workspace-infra/Platform-Orchestrator/issues/1483',
                     'sources': [{'repository': 'other-org/repo'}], 'configurations': [],
                     'gitops': {'repository': 'ai-workspace-infra/gitops'}}
        with self.assertRaisesRegex(ValueError, 'outside approved'):
            module.installation_repositories(candidate, self.trusted.policy_at.return_value,
                                             {'repository': self.env['GITHUB_REPOSITORY']})


class ReadIdentityContractTest(unittest.TestCase):
    def test_only_authenticated_main_evidence_job_can_read_dedicated_path(self):
        role = json.loads((ROOT / 'scripts/vault/roles/github-actions-feature-lane-read-sit.json').read_text())
        claims = role['bound_claims']
        self.assertEqual(claims['repository_id'], '1284966060')
        self.assertEqual(claims['repository_owner_id'], '292703558')
        self.assertEqual(claims['repository'], 'ai-workspace-infra/Platform-Orchestrator')
        self.assertEqual(claims['ref'], 'refs/heads/main')
        self.assertEqual(claims['environment'], 'dev')
        self.assertEqual(claims['job_workflow_ref'], 'ai-workspace-infra/Platform-Orchestrator/.github/workflows/feature-tag-trusted-main.yml@refs/heads/main')
        self.assertEqual(role['token_max_ttl'], '10m')
        self.assertTrue(role['token_no_default_policy'])
        policy = (ROOT / 'scripts/vault/policies/github-actions-feature-lane-read-sit.hcl').read_text()
        self.assertEqual(policy.count('path "'), 1)
        self.assertIn('path "kv/data/sit/platform/github-app/feature-lane"', policy)
        self.assertIn('capabilities = ["read"]', policy)
        workflow = yaml.safe_load((ROOT / '.github/workflows/feature-tag-trusted-main.yml').read_text())
        self.assertNotIn('id-token', workflow['permissions'])
        verify = workflow['jobs']['verify']
        self.assertEqual(verify['needs'], 'event')
        self.assertEqual(verify['environment'], 'dev')
        self.assertEqual(verify['permissions']['id-token'], 'write')
        for name in ('infra', 'services'):
            step = next(s for s in verify['steps'] if s.get('id') == name)
            self.assertTrue(step['with']['repositories'].startswith('${{ needs.event.outputs.'))
            for permission in ('actions', 'contents', 'issues', 'pull-requests'):
                self.assertEqual(step['with']['permission-' + permission], 'read')


if __name__ == '__main__':
    unittest.main()
