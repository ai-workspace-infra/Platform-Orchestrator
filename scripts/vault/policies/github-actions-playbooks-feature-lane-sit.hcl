# Exact Dev target management binding and dedicated read-only registry credential.
path "kv/data/CICD/dev/k3s-bootstrap" {
  capabilities = ["read"]
}
path "kv/data/sit/platform/ghcr/feature-registry" {
  capabilities = ["read"]
}
