import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

root = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('tag_push', root / '.github/scripts/feature-lane/tag-push-preflight.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TagPushTest(unittest.TestCase):
    def test_binding_checks_tag_context_and_target(self):
        with tempfile.TemporaryDirectory() as directory:
            tag = 'smoke-sit-test-1483'
            path = Path(directory) / '.github/feature-candidates' / tag
            path.mkdir(parents=True)
            (path / 'candidate.json').write_text(json.dumps({'feature_tag': tag}))
            (path / 'evidence-selectors.json').write_text('{}')
            env = {'FEATURE_EVENT_TAG': tag, 'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/tags/' + tag,
                   'GITHUB_SHA': 'a'*40, 'GITHUB_WORKSPACE': directory, 'FEATURE_POLICY_COMMIT': 'b'*40,
                   'GITHUB_REPOSITORY': 'ai-workspace-infra/Platform-Orchestrator'}
            trusted = Mock()
            trusted.verify_feature_tag.return_value = {'repository': env['GITHUB_REPOSITORY'], 'target_sha': env['GITHUB_SHA']}
            self.assertEqual(module.check(env, trusted), tag)
            trusted.gate.validate_candidate.assert_called_once()
            for changes in ({'GITHUB_REF': 'refs/heads/main'}, {'GITHUB_EVENT_NAME': 'workflow_dispatch'}, {'GITHUB_SHA': 'c'*40}):
                with self.subTest(changes=changes), self.assertRaises(ValueError): module.check(dict(env, **changes), trusted)
            (path / 'evidence-selectors.json').unlink()
            with self.assertRaises(ValueError): module.check(env, trusted)


if __name__ == '__main__':
    unittest.main()
