# Platform Orchestrator (platform-ops-toolkit) — English Guide

> **Unified Platform Delivery Orchestrator**: Focused on multi-environment (UAT / PROD / SIT) workflow orchestration, quality gating, cloud provider abstraction, and immutable delivery receipt verification.

This file is the explicit English alternate entry point. The canonical English guide is [`README.md`](README.md); the Chinese guide is [`README_zh.md`](README_zh.md).

---

## 🧭 Core Delivery Orchestrators

As the unified control plane for platform engineering, this repository focuses purely on orchestrating multi-environment delivery pipelines:

| Orchestrator | Workflow Entrypoint | Responsibility | Environments |
| :--- | :--- | :--- | :--- |
| **Serverless Orchestrator** | [`.github/workflows/serverless-orchestrator.yml`](.github/workflows/serverless-orchestrator.yml) | Unified serverless delivery (6 stages: Prepare → Database → Backend Matrix → Frontend Matrix → Configure → Summary) | UAT / PROD |
| **Selfhost Orchestrator** | [`.github/workflows/selfhost-orchestrator.yml`](.github/workflows/selfhost-orchestrator.yml) | Multi-cloud VM/K3s provisioning, CMDB tracking, Docker Compose / K3s services rolling upgrades | UAT / PROD |
| **Hybrid Orchestrator** | [`.github/workflows/hybrid-orchestrator.yml`](.github/workflows/hybrid-orchestrator.yml) | Cross-edge elastic scheduling, multi-cloud failover, and dual-active routing | UAT |
| **IaC Orchestrator** | [`.github/workflows/iac-orchestrator.yml`](.github/workflows/iac-orchestrator.yml) | Declarative IaC module dispatch across cloud providers (GCP, AWS, Cloudflare) | Multi-cloud |
| **Daily Main Snapshot** | [`.github/workflows/daily-main-snapshot.yaml`](.github/workflows/daily-main-snapshot.yaml) | Daily immutable snapshot resolution, multi-repo parallel builds, and integration gates | Daily CI |
| **Environment Data Operations** | [`.github/workflows/environment-data-operations.yml`](.github/workflows/environment-data-operations.yml) | Unified database checkpoints, schema migration dispatch, and health probing | UAT / PROD |

> **Documentation Archive**: Historical reference docs, whitepapers, and operational runbooks have been migrated to the knowledge repository: [`ai-workspace-services/knowledge: docs/reference/platform-ops-toolkit/`](https://github.com/ai-workspace-services/knowledge/tree/main/docs/reference/platform-ops-toolkit). Orchestrator howtos remain in [docs/README.md](docs/README.md).

---

## Quick start

1. Prepare a reachable, initialized and unsealed Vault server. The default is [`https://vault.svc.plus`](https://vault.svc.plus).
2. From a checkout of this repository, run [`scripts/create_vault_service_repo_roles.sh`](scripts/create_vault_service_repo_roles.sh) with a Vault administrator token.
3. Verify the result with `./scripts/vault/vault_layout_verify.py`.
4. Open **Actions → Deploy Environment & Provision Infrastructure → Run workflow**.
5. Start with a single domain, matching refs, an immutable `deploy_tag`, `vultr-vps`, and the correct `vault_env_path`.

The selfhost workflow entry point is [`.github/workflows/selfhost-orchestrator.yml`](.github/workflows/selfhost-orchestrator.yml).

## Repository map

| Repository | Role |
| --- | --- |
| [`platform-ops-toolkit`](https://github.com/ai-workspace-infra/platform-ops-toolkit) | GitHub Actions entry point and orchestration |
| [`iac_modules`](https://github.com/ai-workspace-infra/iac_modules) | Terraform modules and cloud resources |
| [`playbooks`](https://github.com/ai-workspace-infra/playbooks) | Ansible OS/application configuration and reusable domain workflows |
| [`gitops`](https://github.com/ai-workspace-infra/gitops) | GitOps environment configuration and desired state |
| [`artifacts`](https://github.com/ai-workspace-infra/artifacts) | Optional images, archives, and release artifacts |

## Vault and permissions

The toolkit authenticates to Vault with GitHub Actions OIDC → Vault JWT. Detailed setup, claims, policies, roles, and KV paths are documented in the [Vault Setup Howto](docs/howto/Vault-Shared-GCP-OIDC-Setup.md) and the [Knowledge Base Archive](https://github.com/ai-workspace-services/knowledge/tree/main/docs/reference/platform-ops-toolkit/04-security-vault-and-iam).

The initializer creates environment policies and two role families:

- `github-actions-platform-ops-toolkit-{sit,uat,prod}` for toolkit workflows.
- `github-actions-playbooks-{sit,uat,prod}` for reusable Playbooks workflows.

The roles are restricted by repository, `job_workflow_ref`, and Git ref. `sit` is for PR/branch validation, `uat` covers the configured UAT branches and snapshot refs, and `prod` currently allows `main` and `v*` tags. The production policy denies KV data and metadata deletion.

## Other operation workflows

- [`data-migration.yaml`](.github/workflows/data-migration.yaml): migration, backup, and restore.
- [`daily-main-snapshot.yaml`](.github/workflows/daily-main-snapshot.yaml): cross-organization snapshot tags and build triggers.
- [`k6-performance-test.yaml`](.github/workflows/k6-performance-test.yaml): k6 load testing.
- [`cron-rotate-domain-tls-certs.yaml`](.github/workflows/cron-rotate-domain-tls-certs.yaml): scheduled or manual TLS certificate rotation.

`daily-main-snapshot.yaml` uses a GitHub App installation token, not only the default `GITHUB_TOKEN`. Install the App in every matrix organization, grant access to the target repositories, and provide at least `Contents: Read and write` and `Actions: Read and write`. The App private key is read from `kv/data/CICD/github-app/daily-snapshot`.

Official references: [GitHub App in Actions](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow), [choosing GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app), and [`actions/create-github-app-token`](https://github.com/actions/create-github-app-token).

## Personal project migration

The workflow is currently wired to `ai-workspace-infra`. To use it for a personal project, replace the hard-coded `iac_modules`, `playbooks`, `gitops`, and reusable workflow references; update service repositories, domains, registries, and GitOps settings; install the GitHub App in the new organizations; and recreate Vault roles and workflow allowlists with the new repository names.

Use this search to find remaining project-specific references:

```bash
rg -n 'ai-workspace-infra|ai-workspace-xstream|compassvpn|svc\.plus|onwalk\.net' \
  .github docs config scripts
```

For the full onboarding guide, parameters, execution flow, environment routing, and troubleshooting, continue to [README.md](README.md).
