import importlib.util
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('artifacts', ROOT / 'scripts/ci/validate_gitops_k3s_artifacts.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GitOpsArtifacts(unittest.TestCase):
    def test_resolve_reuses_the_checked_out_commit(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/selfhost-stage-resolve.yml').read_text())
        steps = workflow['jobs']['resolve-targets']['steps']
        snapshot = next(step for step in steps if step.get('id') == 'gitops_snapshot')
        checkout = next(step for step in steps if step.get('name') == 'Checkout GitOps selfhost routing declaration')
        self.assertLess(steps.index(snapshot), steps.index(checkout))
        self.assertIn('steps.gitops_snapshot.outputs.sha', checkout['with']['ref'])
    def test_digest_required_and_native_targets_do_not_bypass_release_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'cluster').mkdir()
            (root / 'unit').mkdir()
            manifest = root / 'host.yaml'
            manifest.write_text('hosts:\n- host_vars:\n    deployment_mode: kubernetes\n    k3s_platform_flux_root_path: cluster\n')
            (root / 'cluster' / 'unit.yaml').write_text('apiVersion: kustomize.toolkit.fluxcd.io/v1\nkind: Kustomization\nspec:\n  path: unit\n')
            target = root / 'unit' / 'release.yaml'
            target.write_text('apiVersion: source.toolkit.fluxcd.io/v1\nkind: OCIRepository\nmetadata: {name: chart, namespace: app}\nspec:\n  ref:\n    digest: sha256:' + 'a'*64 + '\n---\napiVersion: helm.toolkit.fluxcd.io/v2\nkind: HelmRelease\nmetadata: {name: app, namespace: app}\nspec:\n  chartRef: {kind: OCIRepository, name: chart}\n  values:\n    image: app@sha256:' + 'b'*64 + '\n')
            self.assertTrue(module.validate(root, manifest))
            target.write_text(target.read_text().replace('app@sha256:' + 'b'*64, 'app:latest'))
            with self.assertRaisesRegex(ValueError, 'digest'):
                module.validate(root, manifest)
            manifest.write_text('hosts:\n- host_vars:\n    deployment_mode: native\n')
            self.assertFalse(module.validate(root, manifest))


if __name__ == '__main__':
    unittest.main()
