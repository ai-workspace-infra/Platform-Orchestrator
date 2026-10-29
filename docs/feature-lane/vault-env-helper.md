# Feature lane SIT credential helper

Run `scripts/vault/update-feature-lane-vault.sh` locally after authenticating the Vault CLI. The script reads only the environment variables supplied to it; it does not create or broaden credentials. Do not put tokens in repository files, pull requests, logs or shell history.

| Exported variable | Purpose |
| --- | --- |
| `GHCR_USERNAME`, `GHCR_TOKEN` | One matching classic GitHub identity with exactly `read:packages`; written to the dedicated baseline and SIT runtime KV paths with each owner's field names. |
| `LINODES_TOKEN` | Linode token with exactly `linodes:read_only`; written to the dedicated target path. |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_DNS_TOKEN` | Optional pair for the dedicated DNS path. The operator must separately confirm the token is restricted to the `onwalk.net` zone and required DNS permissions. |

Provide both variables in each pair or neither. A hyphen is not valid in a shell variable name; use the names in the table. Existing KV paths are patched; a new path is created with CAS zero so it cannot overwrite an existing entry. The script validates the GitHub token scope before any writes. It does not independently verify Linode or Cloudflare token scope, GitHub package visibility, workload OIDC access, or a deployed service; verify the Linode and Cloudflare scopes separately before enabling their use.

Avoid entering a literal token in a command line. In an interactive shell, use a silent read before exporting, for example:

```bash
export GHCR_USERNAME='YOUR_GITHUB_USERNAME'
read -rs GHCR_TOKEN; printf '\n'; export GHCR_TOKEN
read -rs LINODES_TOKEN; printf '\n'; export LINODES_TOKEN
scripts/vault/update-feature-lane-vault.sh
unset GHCR_TOKEN LINODES_TOKEN
```

The same GHCR token is placed in two exact KV paths because the baseline producer and the runtime owner have different restricted roles. The baseline fields are `GITHUB_USERNAME` and `GITHUB_TOKEN`; the runtime fields are `GHCR_USERNAME` and `GHCR_TOKEN`. It must be authorized to read all required images. Deploy the baseline consumer change before populating a new path with these fields. The helper does not install the Feature GitHub App into Playbooks, initialize a database, or deploy SIT.
