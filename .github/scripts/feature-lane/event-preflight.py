#!/usr/bin/env python3
"""Bind a tag event to reviewed Main candidate inputs; performs no mutation."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    try:
        tag = os.environ['FEATURE_EVENT_TAG']
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+', tag) or len(tag) > 59:
            raise ValueError('invalid feature tag')
        root = Path(os.environ['GITHUB_WORKSPACE'])
        candidate_dir = root / '.github' / 'feature-candidates' / tag
        candidate_path = candidate_dir / 'candidate.json'
        selector_path = candidate_dir / 'evidence-selectors.json'
        if not candidate_path.is_file() or candidate_path.stat().st_size > 1_000_000:
            raise ValueError('candidate unavailable')
        candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
        if not isinstance(candidate, dict) or candidate.get('feature_tag') != tag:
            raise ValueError('event tag differs from candidate')
        env = dict(os.environ, FEATURE_CANDIDATE_FILE=str(candidate_path),
                   FEATURE_EVIDENCE_SELECTORS_FILE=str(selector_path), FEATURE_STAGE='sit')
        return subprocess.run([sys.executable, str(root / '.github/scripts/feature-lane/preflight.py')], env=env).returncode
    except (KeyError, OSError, ValueError, TypeError):
        print('::error::Feature event could not be bound to a Main candidate', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
