# Dedicated read-only GitHub App; no shared CI or deployment secrets.
path "kv/data/sit/platform/github-app/feature-lane" {
  capabilities = ["read"]
}
