# Read only the three public-key records required by common OS identity setup.
# Vault KV v2 policy paths use /data/. No metadata, list, or write access.
path "kv/data/prod/security/root" {
  capabilities = ["read"]
}

path "kv/data/prod/security/operator" {
  capabilities = ["read"]
}

path "kv/data/prod/security/auditor" {
  capabilities = ["read"]
}
