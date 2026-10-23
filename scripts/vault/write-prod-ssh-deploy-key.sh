#!/usr/bin/env bash
# Update only the two deployment-key fields; secrets travel through stdin.
set -euo pipefail
set +x
umask 077
export VAULT_ADDR="${VAULT_ADDR:-https://vault.svc.plus}"
python3 - <<'PY'
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

def fail(message):
    sys.exit(message)

private = Path.home() / '.ssh/id_ed25519'
public = Path.home() / '.ssh/id_ed25519.pub'
try:
    for path in (private, public):
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
            fail('SSH key files must be regular files owned by the current user.')
    if stat.S_IMODE(private.stat().st_mode) & 0o077:
        fail('Private key permissions must be 0600 or 0400.')
    derived = subprocess.run(['ssh-keygen', '-y', '-f', str(private)], capture_output=True, text=True)
    if derived.returncode:
        fail('Could not derive public key; unlock the private key before retrying.')
    parts = public.read_text().strip().split()
    if len(parts) < 2 or parts[0] != 'ssh-ed25519' or derived.stdout.split()[:2] != parts[:2]:
        fail('The Ed25519 private/public key pair does not match.')
    payload = {
        'SSH_PRIVATE_DEPLOY_KEY_B64': base64.b64encode(private.read_bytes()).decode(),
        'SSH_PUBLIC_DEPLOY_KEY_B64': base64.b64encode(public.read_bytes()).decode(),
    }
    result = subprocess.run(['vault', 'kv', 'patch', 'kv/CICD/prod', '-'],
                            input=json.dumps(payload), text=True, capture_output=True)
    if result.returncode:
        fail('Vault patch failed; check Vault authentication, path and patch permission. Secret output withheld.')
    print('Updated kv/CICD/prod: SSH_PRIVATE_DEPLOY_KEY_B64, SSH_PUBLIC_DEPLOY_KEY_B64.')
except (OSError, ValueError):
    fail('Key update failed; private diagnostics withheld.')
PY
