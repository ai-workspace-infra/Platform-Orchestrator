# Only the dedicated identity, never the shared Vault auth mount or secret data.
path "sys/auth" {
  capabilities = ["read"]
}
path "sys/auth/jwt-prod-k3s-v6" {
  # Vault requires sudo to enable an auth method; scope it to this dedicated mount only.
  capabilities = ["create", "update", "sudo"]
}
path "sys/policies/acl/prod-k3s-v6-vault-tls-reader" {
  capabilities = ["read", "create", "update"]
}
path "auth/jwt-prod-k3s-v6/config" {
  capabilities = ["create", "read", "update"]
}
path "auth/jwt-prod-k3s-v6/role/prod-k3s-v6-vault-tls-reader" {
  capabilities = ["create", "read", "update"]
}
path "auth/token/lookup-self" {
  capabilities = ["read"]
}
