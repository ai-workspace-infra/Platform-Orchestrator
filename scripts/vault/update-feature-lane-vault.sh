#!/usr/bin/env bash
# Update the dedicated SIT credential paths from exported environment variables.
# No credential values are printed or passed as command-line arguments.
set -euo pipefail
umask 077
export VAULT_ADDR="${VAULT_ADDR:-https://vault.svc.plus}"

for program in vault python3; do
  command -v "$program" >/dev/null 2>&1 || { printf 'Missing required program: %s\n' "$program" >&2; exit 1; }
done
vault token lookup >/dev/null 2>&1 || { printf 'Vault login is unavailable.\n' >&2; exit 1; }

if [[ -n "${GHCR_USERNAME:-}" && -z "${GHCR_TOKEN:-}" ]] || [[ -z "${GHCR_USERNAME:-}" && -n "${GHCR_TOKEN:-}" ]]; then
  printf 'GHCR_USERNAME and GHCR_TOKEN must be supplied together.\n' >&2; exit 1
fi
if [[ -n "${CLOUDFLARE_ACCOUNT_ID:-}" && -z "${CLOUDFLARE_DNS_TOKEN:-}" ]] || [[ -z "${CLOUDFLARE_ACCOUNT_ID:-}" && -n "${CLOUDFLARE_DNS_TOKEN:-}" ]]; then
  printf 'CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_DNS_TOKEN must be supplied together.\n' >&2; exit 1
fi
if [[ -z "${GHCR_TOKEN:-}" && -z "${LINODES_TOKEN:-}" && -z "${CLOUDFLARE_DNS_TOKEN:-}" ]]; then
  printf 'No credential environment variables were supplied.\n' >&2; exit 1
fi
if [[ -n "${CLOUDFLARE_ACCOUNT_ID:-}" && ! "${CLOUDFLARE_ACCOUNT_ID}" =~ ^[0-9a-fA-F]{32}$ ]]; then
  printf 'CLOUDFLARE_ACCOUNT_ID must be 32 hexadecimal characters.\n' >&2; exit 1
fi

# Validate the GHCR identity before any write. Linode token scope is not
# introspectable with this input and requires independent operator verification.
python3 "$(dirname "$0")/validate-feature-lane-tokens.py"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/feature-lane-vault.XXXXXX")"
cleanup() { rm -rf -- "$tmp_dir"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

write_path() {
  local path="$1"; shift
  if vault kv metadata get -format=json "$path" >/dev/null 2>&1; then
    vault kv patch "$path" "$@" >/dev/null
  else
    # CAS=0 prevents overwriting an existing path even if metadata access fails.
    vault kv put -cas=0 "$path" "$@" >/dev/null
  fi
  printf 'Updated %s\n' "$path"
}
if [[ -n "${GHCR_TOKEN:-}" ]]; then
  printf '%s' "$GHCR_TOKEN" > "$tmp_dir/ghcr"
  write_path kv/sit/platform/ghcr/feature-baseline "username=$GHCR_USERNAME" "token=@$tmp_dir/ghcr"
  write_path kv/sit/platform/ghcr/feature-registry "GHCR_USERNAME=$GHCR_USERNAME" "GHCR_TOKEN=@$tmp_dir/ghcr"
fi
if [[ -n "${LINODES_TOKEN:-}" ]]; then
  printf '%s' "$LINODES_TOKEN" > "$tmp_dir/linodes"
  write_path kv/sit/platform/akamai/feature-target "token=@$tmp_dir/linodes"
fi
if [[ -n "${CLOUDFLARE_DNS_TOKEN:-}" ]]; then
  printf '%s' "$CLOUDFLARE_DNS_TOKEN" > "$tmp_dir/cloudflare"
  write_path kv/sit/platform/cloudflare/feature-dns "account_id=$CLOUDFLARE_ACCOUNT_ID" "token=@$tmp_dir/cloudflare"
  printf 'Cloudflare zone scope must be verified separately before use.\n'
fi
printf 'Credential values were not printed. Workflow access and image permissions require separate verification.\n'
