"""Gate adversarial tests; fixtures are synthetic and prove no runtime acceptance."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / '.github/scripts/acceptance/verify_receipt.py'
spec = importlib.util.spec_from_file_location('evidence_receipt', SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.fixture
def case(tmp_path):
    request = {key: 'identity' for key in gate.IDENTITY}
    request.update(environment='uat', owner='playbooks', artifact_digest='sha256:' + 'd'*64)
    for key in gate.SHAS:
        request[key] = 'a'*40
    for key in gate.IDENTITY:
        if key.endswith(('run_id', 'run_attempt')) or key == 'artifact_id':
            request[key] = '1'
    request['required_checks'] = ['V5-06', 'V5-11']
    request.update(not_before='2026-10-25T01:00:00Z', not_after='2026-10-25T02:00:00Z')
    evidence = tmp_path / 'checks.json'
    evidence.write_text('{"sanitized":true}\n')
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    receipt = dict(schema_version='v5-acceptance/v1', identity={k: request[k] for k in gate.IDENTITY},
                   started_at='2026-10-25T01:01:00Z', finished_at='2026-10-25T01:02:00Z',
                   checks=[dict(id=c, status='PASS', evidence='checks.json', sha256=digest)
                           for c in request['required_checks']], result='PASS')
    return receipt, request, tmp_path


def test_exact_receipt(case):
    assert gate.validate(*case)['result'] == 'PASS'


@pytest.mark.parametrize('key', sorted(gate.IDENTITY))
def test_wrong_or_missing_identity(case, key):
    receipt, request, root = case
    for operation in ('wrong', 'missing'):
        bad = copy.deepcopy(receipt)
        if operation == 'wrong':
            bad['identity'][key] = 'wrong'
        else:
            del bad['identity'][key]
        with pytest.raises(ValueError):
            gate.validate(bad, request, root)


@pytest.mark.parametrize('status', ['FAIL', 'PARTIAL', 'SKIPPED', 'NOT_RUN', 'UNKNOWN', None, True])
def test_required_nonpass(case, status):
    receipt, request, root = case
    receipt['checks'][0]['status'] = status
    with pytest.raises(ValueError):
        gate.validate(receipt, request, root)


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unexpected', 'empty', 'result', 'schema', 'unknown_field'])
def test_incomplete_or_contradictory(case, change):
    receipt, request, root = case
    if change == 'missing': receipt['checks'].pop()
    if change == 'duplicate': receipt['checks'][1] = receipt['checks'][0]
    if change == 'unexpected': receipt['checks'][0]['id'] = 'V5-23'
    if change == 'empty': receipt['checks'] = []
    if change == 'result': receipt['result'] = 'FAIL'
    if change == 'schema': receipt['schema_version'] = 'v0'
    if change == 'unknown_field': receipt['raw_secret'] = 'synthetic'
    with pytest.raises(ValueError):
        gate.validate(receipt, request, root)


@pytest.mark.parametrize('path', ['../escape', '/tmp/escape', './checks.json', 'a/../checks.json', 'a\\checks.json', ''])
def test_unsafe_paths(case, path):
    receipt, request, root = case
    receipt['checks'][0]['evidence'] = path
    with pytest.raises(ValueError): gate.validate(receipt, request, root)


@pytest.mark.parametrize('kind', ['missing', 'empty', 'changed', 'symlink'])
def test_artifact_not_real(case, kind):
    receipt, request, root = case
    path = root / 'checks.json'
    if kind == 'missing': path.unlink()
    if kind == 'empty': path.write_text('')
    if kind == 'changed': path.write_text('tampered')
    if kind == 'symlink':
        path.rename(root / 'other.json')
        path.symlink_to(root / 'other.json')
    with pytest.raises((ValueError, OSError)): gate.validate(receipt, request, root)


@pytest.mark.parametrize('value', [[], ['V5-06', 'V5-06'], ['invalid'], None])
def test_invalid_required_set(case, value):
    receipt, request, root = case
    request['required_checks'] = value
    with pytest.raises(ValueError): gate.validate(receipt, request, root)


@pytest.mark.parametrize('content', [None, 'broken', '[]', '{"x":1,"x":2}', '{"result":"PASS"}'])
def test_cli_missing_invalid_never_success(case, content):
    receipt, request, root = case
    request_path = root / 'request.json'
    request_path.write_text(json.dumps(request))
    receipt_path = root / 'receipt.json'
    if content is not None: receipt_path.write_text(content)
    result = subprocess.run([sys.executable, str(SCRIPT), '--request', str(request_path),
                             '--receipt', str(receipt_path), '--evidence-root', str(root)], capture_output=True, text=True)
    assert result.returncode == 1
    assert not result.stdout
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('key,value', [('started_at', '2026-10-24T01:00:00Z'), ('finished_at', '2026-10-25T03:00:00Z'), ('finished_at', 'bad'), ('started_at', '2026-10-25T01:01:00'), ('finished_at', None)])
def test_bad_execution_window(case, key, value):
    receipt, request, root = case
    receipt[key] = value
    with pytest.raises(ValueError): gate.validate(receipt, request, root)
