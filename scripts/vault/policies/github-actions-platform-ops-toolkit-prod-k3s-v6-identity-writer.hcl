# Initial issuance only. CAS=0 is enforced by the Playbooks node-side writer.
# No update/delete/list/metadata access; no other identity policy is inherited.
path "kv/data/prod/prod-k3s-v6/root" {
  capabilities = ["create", "read"]
}
path "kv/data/prod/prod-k3s-v6/operator" {
  capabilities = ["create", "read"]
}
path "kv/data/prod/prod-k3s-v6/auditor" {
  capabilities = ["create", "read"]
}
