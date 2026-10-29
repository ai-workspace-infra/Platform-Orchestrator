import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('chart', ROOT / '.github/scripts/feature-lane/chart.py')
chart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chart)


class ChartEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.producer = 'a' * 40
        self.current = 'b' * 40
        self.package = b'chart-package'
        self.package_sha = hashlib.sha256(self.package).hexdigest()
        self.policy = {'chart_owner': {'repository': chart.REPO, 'workflow': chart.WORKFLOW,
                                       'package': 'distributed-web-saas-fullstack-0.2.9.tgz'}}
        self.candidate = {'sources': [{'repository': chart.REPO, 'sha': self.current}], 'chart_digest': 'sha256:' + 'c' * 64}
        self.selector = {'run_id': 42, 'attempt': 1, 'artifact_id': 99}
        self.run = {'id': 42, 'run_attempt': 1, 'event': 'push', 'head_branch': 'main', 'head_sha': self.producer,
                    'path': chart.WORKFLOW, 'status': 'completed', 'conclusion': 'success',
                    'repository': {'full_name': chart.REPO}, 'head_repository': {'full_name': chart.REPO}}
        self.reader = Mock()
        self.reader.api.side_effect = lambda path: {'status': 'ahead'} if '/compare/' in path else self.run
        manifest = {'source_sha': self.producer, 'packages': {self.policy['chart_owner']['package']: self.package_sha}}
        self.reader.artifact_file.side_effect = lambda *args: json.dumps(manifest).encode() if args[5] == 'source-manifest.json' else self.package
        self.registry = Mock(return_value={'schemaVersion': 2, 'layers': [{'mediaType': 'application/vnd.cncf.helm.chart.content.v1.tar+gzip',
                                                                           'digest': 'sha256:' + self.package_sha, 'size': len(self.package)}]})
        self.file_at = Mock(return_value='d' * 64)

    def verify(self):
        return chart.verify(self.candidate, self.policy, self.selector, self.reader, self.file_at, self.registry)

    def test_chart_matches_authenticated_run_tree_and_registry_layer(self):
        with patch.object(chart, 'tree_at', return_value='e' * 40):
            result = self.verify()
        self.assertEqual(result['producer_sha'], self.producer)
        self.assertEqual(result['candidate_source_sha'], self.current)
        self.assertEqual(result['package_sha256'], self.package_sha)

    def test_candidate_may_select_only_reviewed_package(self):
        name = 'distributed-web-saas-fullstack-0.2.10.tgz'
        self.policy['chart_owner']['additional_packages'] = [name]
        self.candidate['chart_package'] = name
        manifest = {'source_sha':self.producer, 'packages':{name:self.package_sha}}
        self.reader.artifact_file.side_effect = lambda *args: json.dumps(manifest).encode() if args[5] == 'source-manifest.json' else self.package
        with patch.object(chart, 'tree_at', return_value='e'*40):
            self.assertEqual(self.verify()['package_sha256'], self.package_sha)
            self.candidate['chart_package'] = 'distributed-web-saas-fullstack-0.3.0.tgz'
            with self.assertRaisesRegex(ValueError, 'not reviewed'):
                self.verify()
        self.policy['chart_owner']['additional_packages'] = [name, name]
        with self.assertRaisesRegex(ValueError, 'package list'):
            self.verify()

    def test_rejects_changed_tree_run_or_registry_package(self):
        with patch.object(chart, 'tree_at', side_effect=['e' * 40, 'f' * 40]):
            with self.assertRaisesRegex(ValueError, 'tree changed'):
                self.verify()
        self.run['head_repository'] = {'full_name': 'foreign/fork'}
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.verify()
        self.run['head_repository'] = {'full_name': chart.REPO}
        self.registry.return_value['layers'][0]['digest'] = 'sha256:' + 'f' * 64
        with patch.object(chart, 'tree_at', return_value='e' * 40):
            with self.assertRaisesRegex(ValueError, 'differs'):
                self.verify()


if __name__ == '__main__':
    unittest.main()
