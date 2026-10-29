# Dedicated read-only Dev target identity; no cloud write or DNS credentials.
path "kv/data/sit/platform/akamai/feature-target" {
  capabilities = ["read"]
}
