# Dedicated SIT baseline pull credential; no registry write or adjacent secrets.
path "kv/data/sit/platform/ghcr/feature-baseline" {
  capabilities = ["read"]
}
