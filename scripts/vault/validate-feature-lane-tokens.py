#!/usr/bin/env python3
"""Validate exported identities without disclosing tokens or response bodies."""
import json
import os
import sys
import urllib.request


def profile(url, token):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response), response.headers


def main(env):
    token = env.get('GHCR_TOKEN', '')
    username = env.get('GHCR_USERNAME', '')
    if token:
        if any(c in username + token for c in '\r\n'):
            raise ValueError('invalid GHCR identity')
        user, headers = profile('https://api.github.com/user', token)
        scopes = {s.strip() for s in headers.get('X-OAuth-Scopes', '').split(',') if s.strip()}
        if scopes != {'read:packages'} or user.get('login', '').lower() != username.lower():
            raise ValueError('GHCR credential must match username and have only read:packages')
        print('GHCR identity and read:packages-only scope verified')
    token = env.get('LINODES_TOKEN', '')
    if token:
        if '\n' in token or '\r' in token:
            raise ValueError('invalid Linode identity')
        print('Linode token scope is not verified; confirm linodes:read_only separately')

if __name__ == '__main__':
    try:
        main(os.environ)
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print('Credential validation failed: ' + message, file=sys.stderr)
        sys.exit(1)
