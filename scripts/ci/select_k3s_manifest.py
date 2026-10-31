#!/usr/bin/env python3
"""Select a K3s resource declaration using the reviewed IaC target and CMDB host."""
import json
from pathlib import Path
import sys

import yaml


def select(checkout, target_path, cmdb_path, host):
    root = Path(checkout).resolve()
    node = json.loads(Path(cmdb_path).read_text())[host]
    if node.get('host_vars', {}).get('deployment_mode', node.get('deployment_mode')) != 'kubernetes':
        return None
    target = (root / target_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError('IaC target declaration must be inside the GitOps checkout')
    candidates = []
    for entry in yaml.safe_load(target.read_text())['targets']:
        path = entry['stages']['resources']['manifest']
        resource = (root / path).resolve()
        if not resource.is_relative_to(root) or not resource.is_file():
            raise ValueError('resource declaration must be inside the GitOps checkout')
        document = yaml.safe_load(resource.read_text())
        matches = [item for item in document.get('hosts', []) if item.get('name') == host]
        if matches:
            if len(matches) != 1 or matches[0].get('host_vars', {}).get('deployment_mode') != 'kubernetes':
                raise ValueError('ambiguous or non-Kubernetes host declaration')
            candidates.append(path)
    if len(candidates) != 1:
        raise ValueError('expected exactly one matching target resource declaration')
    return candidates[0]


if __name__ == '__main__':
    result = select(*sys.argv[1:])
    print(result or '')
