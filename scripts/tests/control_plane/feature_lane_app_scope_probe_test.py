import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('app_probe', ROOT / '.github/scripts/feature-lane/app-scope-probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

def payload(names):
    return Response(json.dumps({'total_count': len(names), 'repositories': [{'full_name': name} for name in names]}).encode())

class ScopeTest(unittest.TestCase):
    def test_both_exact_scopes_required(self):
        with patch.dict(os.environ, {'INFRA_TOKEN': 'one', 'SERVICES_TOKEN': 'two'}):
            with patch.object(probe.urllib.request, 'urlopen', side_effect=[payload(probe.EXPECTED['INFRA_TOKEN']), payload(probe.EXPECTED['SERVICES_TOKEN'])]):
                probe.main()
            with patch.object(probe.urllib.request, 'urlopen', side_effect=[payload(probe.EXPECTED['INFRA_TOKEN'] | {'foreign/repo'})]):
                with self.assertRaises(ValueError): probe.main()

if __name__ == '__main__': unittest.main()
