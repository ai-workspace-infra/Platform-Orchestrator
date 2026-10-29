#!/usr/bin/env python3
"""Validate the fixed candidate's rendered lane before publishing DNS."""
import json
import os
from pathlib import Path
import re
import sys


def verify(receipt, candidate_root, validator):
    if (receipt.get('schema_version') != 'dev-feature-candidate/v2' or receipt.get('result') != 'verified' or
        receipt.get('stage') != 'sit' or receipt.get('repository') != 'ai-workspace-infra/gitops' or
        not re.fullmatch(r'[0-9a-f]{40}', str(receipt.get('candidate_head', ''))) or
        not isinstance(receipt.get('projection'), dict)):
        raise ValueError('invalid verified candidate receipt')
    return validator.validate_tree(candidate_root, receipt['candidate_head'], 'sit', candidate=receipt['projection'])


def main():
    try:
        owner = Path(os.environ['VALIDATOR_ROOT']).resolve()
        sys.path.insert(0, str(owner / 'scripts'))
        import dev_feature_candidate
        receipt = json.loads(Path(os.environ['FEATURE_RECEIPT_FILE']).read_text())
        result = verify(receipt, os.environ['FEATURE_GITOPS_ROOT'], dev_feature_candidate)
        print('Validated candidate manifest before DNS; SHA256:', result['manifest_sha256'])
        return 0
    except Exception as error:
        message = ('Candidate knowledge revision differs from rendered GitOps; freeze a corrected candidate.'
                   if str(error) == 'runtime knowledge source differs from authenticated candidate'
                   else 'Candidate manifest failed pre-DNS validation')
        print('::error::' + message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
