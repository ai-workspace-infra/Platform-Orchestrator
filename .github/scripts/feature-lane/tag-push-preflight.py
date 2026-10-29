#!/usr/bin/env python3
"""Authenticate a pushed tag against reviewed Main; no cross-repo acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import re


def check(env, trusted):
    tag = env.get('FEATURE_EVENT_TAG', '')
    if (env.get('GITHUB_EVENT_NAME') != 'push' or env.get('GITHUB_REF') != 'refs/tags/' + tag or
        not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+', tag) or len(tag) > 59 or
        not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', ''))):
        raise ValueError('invalid tag push')
    root = Path(env['GITHUB_WORKSPACE']) / '.github' / 'feature-candidates' / tag
    if root.is_symlink():
        raise ValueError('candidate directory must not be a symlink')
    files = [root / 'candidate.json', root / 'evidence-selectors.json']
    if any(path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000 for path in files):
        raise ValueError('reviewed candidate files required')
    candidate, selectors = (json.loads(path.read_text(encoding='utf-8')) for path in files)
    if not isinstance(candidate, dict) or not isinstance(selectors, dict) or candidate.get('feature_tag') != tag:
        raise ValueError('candidate tag mismatch')
    policy = trusted.policy_at(env['FEATURE_POLICY_COMMIT'])
    trusted.gate.validate_candidate(candidate, policy)
    binding = trusted.verify_feature_tag(candidate, policy)
    if (binding.get('repository', '').lower() != env.get('GITHUB_REPOSITORY', '').lower() or
            binding.get('target_sha') != env['GITHUB_SHA']):
        raise ValueError('tag target mismatch')
    return tag


def main():
    spec = importlib.util.spec_from_file_location('trusted_feature', Path(__file__).with_name('trusted.py'))
    trusted = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trusted)
    try:
        check(os.environ, trusted)
        print('Tag and reviewed Main candidate binding verified; cross-repository evidence remains pending.')
    except (KeyError, OSError, ValueError, TypeError):
        raise SystemExit('::error::Tag push could not be bound to reviewed Main candidate') from None


if __name__ == '__main__':
    main()
