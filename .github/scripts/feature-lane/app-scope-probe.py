#!/usr/bin/env python3
"""Confirm each installation token sees exactly the reviewed repositories."""
import json
import os
import sys
import urllib.request

EXPECTED = {
    'INFRA_TOKEN': {'ai-workspace-infra/platform-orchestrator', 'ai-workspace-infra/artifacts', 'ai-workspace-infra/gitops',
                    'ai-workspace-infra/playbooks'},
    'SERVICES_TOKEN': {'ai-workspace-services/portal', 'ai-workspace-services/accounts', 'ai-workspace-services/billing-service',
                       'ai-workspace-services/content-service', 'ai-workspace-services/postgresql', 'ai-workspace-services/knowledge'},
}

def main():
    for key, expected in EXPECTED.items():
        request = urllib.request.Request('https://api.github.com/installation/repositories?per_page=100',
            headers={'Authorization': 'Bearer ' + os.environ[key], 'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
        rows = data.get('repositories', [])
        if data.get('total_count') != len(expected) or {r.get('full_name', '').lower() for r in rows} != expected:
            raise ValueError('installation token scope mismatch')
    print('PASS: both installation tokens match the reviewed repository sets')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('::error::Scoped App token verification failed', file=sys.stderr)
        sys.exit(1)
