#!/usr/bin/env python3
"""Exercise the exact workload identity without printing tokens or secret data."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://vault.svc.plus/v1/'
ROLE = 'github-actions-feature-lane-read-sit'

def request(url, *, headers=None, body=None):
    req = urllib.request.Request(url, headers=headers or {}, data=body, method='POST' if body is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read(100000)
    except urllib.error.HTTPError as error:
        return error.code, b''

def main(mode):
    if mode not in ('allowed', 'denied-environment', 'denied-caller', 'deploy-allowed', 'deploy-denied', 'target-denied'):
        raise ValueError('invalid probe mode')
    oidc_url = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']
    separator = '&' if '?' in oidc_url else '?'
    status, data = request(oidc_url + separator + urllib.parse.urlencode({'audience': 'vault'}),
                           headers={'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    if status != 200:
        raise ValueError('GitHub identity unavailable')
    jwt = json.loads(data)['value']
    role = ('github-actions-feature-lane-deploy-evidence-read-sit' if mode.startswith('deploy-') else
            'github-actions-feature-target-read-sit' if mode == 'target-denied' else ROLE)
    status, data = request(BASE + 'auth/jwt/login', headers={'Content-Type': 'application/json'},
                           body=json.dumps({'role': role, 'jwt': jwt}).encode())
    if mode in ('denied-environment', 'denied-caller', 'deploy-denied', 'target-denied'):
        if status not in (400, 403):
            raise ValueError('invalid workload identity was not denied')
        print('PASS: invalid workload identity denied')
        return
    if status != 200:
        raise ValueError('intended workload login denied')
    token = json.loads(data)['auth']['client_token']
    headers = {'X-Vault-Token': token}
    allowed, _ = request(BASE + 'kv/data/sit/platform/github-app/feature-lane', headers=headers)
    denied, _ = request(BASE + 'kv/data/sit/platform/github-app/feature-lane-probe-denied', headers=headers)
    if allowed != 200 or denied != 403:
        raise ValueError('Vault path access did not meet expected contract')
    print('PASS: intended path readable; adjacent path denied')

if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except (KeyError, IndexError, ValueError, OSError, json.JSONDecodeError):
        print('::error::Vault workload identity probe failed', file=sys.stderr)
        sys.exit(1)
