#!/usr/bin/env python3
"""Read-only trusted feature candidate verification entry point.

Files supplied here are untrusted declarations and selectors, never evidence.
The verifier fetches evidence and reviewed policy through its GitHub adapter.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys


def read_json(path):
    source = Path(path)
    if not source.is_file() or source.stat().st_size > 1_000_000:
        raise ValueError('missing or oversized input')
    return json.loads(source.read_text(encoding='utf-8'))


def main():
    spec = importlib.util.spec_from_file_location('feature_gate', Path(__file__).with_name('gate.py'))
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    try:
        candidate = read_json(os.environ['FEATURE_CANDIDATE_FILE'])
        selectors = read_json(os.environ['FEATURE_EVIDENCE_SELECTORS_FILE'])
        result = gate.gate(candidate, stage=os.environ['FEATURE_STAGE'],
                           policy_commit=os.environ['FEATURE_POLICY_COMMIT'], evidence_selectors=selectors)
        if result.get('status') != 'VERIFIED_GATE' or result.get('dispatch_authorized') is not False:
            raise ValueError('unexpected verifier result')
        print(json.dumps(result, sort_keys=True))
        return 0
    except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError):
        print('::error::Feature candidate verification failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
