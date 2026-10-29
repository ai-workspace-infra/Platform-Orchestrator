# The seed owner reads only the exact Dev management binding.
path "kv/data/CICD/dev/k3s-bootstrap" {
  capabilities = ["read"]
}
