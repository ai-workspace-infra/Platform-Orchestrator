#!/usr/bin/env python3
"""Offline evidence gate. Expected identity must come from trusted dispatch metadata."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

IDENTITY = {'environment', 'cluster', 'host_id', 'owner', 'workflow', 'parent_run_id',
            'parent_run_attempt', 'child_run_id', 'child_run_attempt', 'toolkit_sha',
            'gitops_sha', 'iac_sha', 'playbooks_sha', 'release_sha', 'artifact_digest',
            'artifact_id'}
SHAS = {'toolkit_sha', 'gitops_sha', 'iac_sha', 'playbooks_sha', 'release_sha'}


def reject(message):
    raise ValueError(message)


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            reject('duplicate JSON key')
        result[key] = value
    return result


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=object_pairs)


def validate(receipt, expected, root):
    if not isinstance(expected, dict) or set(expected) != IDENTITY | {'required_checks', 'not_before', 'not_after'}:
        reject('invalid trusted request fields')
    for key in IDENTITY:
        value = expected[key]
        if type(value) is not str or not value or value.strip() != value:
            reject('empty or invalid trusted identity')
        if key in SHAS and not re.fullmatch('[0-9a-f]{40}', value):
            reject('immutable SHA required')
        if key.endswith(('run_id', 'run_attempt')) or key == 'artifact_id':
            if not re.fullmatch('[1-9][0-9]*', value):
                reject('positive run, attempt and artifact IDs required')
    if expected['environment'] not in {'sit', 'uat', 'prod'}:
        reject('invalid environment')
    if expected['owner'] not in {'playbooks', 'iac_modules', 'platform-ops-toolkit'}:
        reject('invalid owner')
    if not re.fullmatch('sha256:[0-9a-f]{64}', expected['artifact_digest']):
        reject('immutable artifact digest required')
    required = expected['required_checks']
    if (not isinstance(required, list) or not required or
            any(type(c) is not str or not re.fullmatch(r'V5-(?:0[1-9]|1[0-9]|2[0-3])', c) for c in required)
            or len(set(required)) != len(required)):
        reject('nonempty unique required checks required')
    if not isinstance(receipt, dict) or set(receipt) != {'schema_version', 'identity', 'checks', 'result', 'started_at', 'finished_at'}:
        reject('invalid receipt fields')
    if receipt['schema_version'] != 'v5-acceptance/v1':
        reject('unsupported receipt schema')
    if receipt['identity'] != {key: expected[key] for key in IDENTITY}:
        reject('receipt identity mismatch')
    def timestamp(value):
        if type(value) is not str:
            reject('timestamp required')
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            reject('UTC timestamp required')
        return parsed
    before, after = timestamp(expected['not_before']), timestamp(expected['not_after'])
    started, finished = timestamp(receipt['started_at']), timestamp(receipt['finished_at'])
    if not before <= started <= finished <= after:
        reject('receipt outside trusted execution window')
    checks = receipt['checks']
    if not isinstance(checks, list) or len(checks) != len(required):
        reject('incomplete check coverage')
    seen = set()
    root = Path(root).resolve(strict=True)
    for check in checks:
        if not isinstance(check, dict) or set(check) != {'id', 'status', 'evidence', 'sha256'}:
            reject('invalid check fields')
        check_id = check['id']
        if type(check_id) is not str or check_id not in required or check_id in seen:
            reject('unexpected or duplicate check')
        seen.add(check_id)
        if check['status'] != 'PASS':
            reject('required check did not PASS')
        value = check['evidence']
        if type(value) is not str or not value or '\\' in value:
            reject('invalid evidence path')
        relative = PurePosixPath(value)
        if relative.is_absolute() or '..' in relative.parts or str(relative) != value:
            reject('unsafe evidence path')
        evidence = root / value
        if any(part.is_symlink() for part in [evidence, *evidence.parents] if part != root and root in part.parents):
            reject('symlink evidence forbidden')
        evidence = evidence.resolve(strict=True)
        if not evidence.is_relative_to(root) or not evidence.is_file() or evidence.stat().st_size == 0:
            reject('missing or empty evidence')
        if type(check['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', check['sha256']):
            reject('invalid evidence digest')
        if hashlib.sha256(evidence.read_bytes()).hexdigest() != check['sha256']:
            reject('evidence digest mismatch')
    if seen != set(required) or receipt['result'] != 'PASS':
        reject('inconsistent receipt result')
    return {'schema_version': receipt['schema_version'], 'result': 'PASS', 'checks': sorted(seen)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--request', required=True)
    parser.add_argument('--evidence-root', required=True)
    args = parser.parse_args()
    try:
        result = validate(load(args.receipt), load(args.request), args.evidence_root)
    except (ValueError, OSError, TypeError, KeyError):
        parser.exit(1, 'Evidence rejected: missing, invalid, mismatched or incomplete receipt.\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
