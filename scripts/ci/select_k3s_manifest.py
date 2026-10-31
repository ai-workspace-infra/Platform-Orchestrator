#!/usr/bin/env python3
"""Select a K3s resource declaration using the reviewed IaC target and CMDB host."""
import json
import re
from pathlib import Path
import sys

import yaml


def select(checkout, target_path, cmdb_path, host, environment='', provider='', account='', workspace=''):
    root = Path(checkout).resolve()
    node = json.loads(Path(cmdb_path).read_text())[host]
    if node.get('host_vars', {}).get('deployment_mode', node.get('deployment_mode')) != 'kubernetes':
        return None
    target = (root / target_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError('IaC target declaration must be inside the GitOps checkout')
    declaration = yaml.safe_load(target.read_text())
    if declaration.get('kind') == 'IaCTargetCatalog':
        if not all((environment, provider, account, workspace)):
            raise ValueError('catalog selection requires the full IaC target scope')
        target_paths = declaration.get('target_manifests', [])
        if not target_paths:
            raise ValueError('empty IaC target catalog')
    else:
        target_paths = [target_path]
    candidates = []
    for selected_path in target_paths:
        target_file = (root / selected_path).resolve()
        if not target_file.is_relative_to(root) or not target_file.is_file():
            raise ValueError('target declaration must be inside the GitOps checkout')
        for entry in yaml.safe_load(target_file.read_text()).get('targets', []):
            if environment and (entry.get('environment'), entry.get('provider'), entry.get('account'), entry.get('workspace')) != (environment, provider, account, workspace):
                continue
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


def writer_role(checkout, resource_path, host):
    root = Path(checkout).resolve()
    path = (root / resource_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('resource declaration must be inside the GitOps checkout')
    document = yaml.safe_load(path.read_text())
    matches = [item for item in document.get('hosts', []) if item.get('name') == host]
    if len(matches) != 1:
        raise ValueError('expected exactly one host')
    role = matches[0].get('host_vars', {}).get('k3s_identity_vault_writer_role', '')
    if not isinstance(role, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]+', role):
        raise ValueError('a valid declared Vault writer role is required')
    return role


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--writer-role':
        print(writer_role(*sys.argv[2:]))
    else:
        print(select(*sys.argv[1:]) or '')
