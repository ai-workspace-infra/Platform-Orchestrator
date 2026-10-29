# Dedicated SIT DNS identity; the provider credential is separately zone-scoped.
path "kv/data/sit/platform/cloudflare/feature-dns" {
  capabilities = ["read"]
}
