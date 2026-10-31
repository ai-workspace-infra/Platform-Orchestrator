# Selfhost Orchestrator dispatch inputs

The form is defined by `.github/workflows/selfhost-orchestrator.yml`. Infrastructure repositories resolve to the selected `source_ref`; an empty value means `main`. Application artifacts use `deploy_tag` independently.

The form now has 22 inputs, below GitHub's 25-input limit.

## Operation contract

| `operation` | Meaning | Execution boundary |
| --- | --- | --- |
| `plan` | 校验 | Resolve and validate the request, then create an IaC plan. |
| `infra` | 基础设施 | Apply infrastructure and run platform bootstrap; do not deploy application images. |
| `deploy` | 基础设施 + 部署 | Apply infrastructure and deploy the selected application domain. |
| `deploy+init` | 空库初始化 + 部署 | Initialize an empty database and deploy; currently restricted by the resolver to UAT `web-saas`. |
| `deploy+migrate` | 部署 + 迁移 | Apply infrastructure, deploy, then run the supported migration flow. |
| `migrate` | 仅迁移 | Run the supported migration flow without applying infrastructure or deploying application images. |
| `destroy` | 销毁 | Request infrastructure destruction; existing production and persistent-service protections still apply. |

These values are the public operation contract. Keep the choices and their routing aligned when changing the workflow.

## Dispatch inputs

| Input | Purpose | Default / behavior |
| --- | --- | --- |
| `runner_type` | Runner selection | `ubuntu-latest` |
| `operation` | Select the operation above | `plan` |
| `target_domains` | Business domain selection | `web-saas` |
| `vault_env_path` | Environment and isolated generation profile | `uat` |
| `source_ref` | Infrastructure repository ref | Empty resolves to `main`; business artifacts use `deploy_tag`. |
| `deploy_tag` | Immutable application artifact version | Required for `deploy`, `deploy+init`, and `deploy+migrate`; may be empty for other operations. |
| `cloud_provider` | Provider adapter | `gcp-cloud` |
| `cloud_account` | Provider account name or ID, including Akamai accounts | Empty selects the environment profile account. |
| `instance_plan` | Main resource size | `2C4G` |
| `agent_proxy_plan` | Agent Proxy resource size | `1C2G` |
| `include_external_agent_proxy` | Include the separately declared external Agent Proxy | `true` |
| `dns_mode` | DNS mutation scope | `none` |
| `offline_mode` | On-host package delivery | `off` |
| `skip_stripe_catalog` | Skip optional Stripe Catalog synchronization | `false` |
| `open_platform_service` | Legacy Open Platform service selector | `none` |
| `source_host` | Source host for migration/export operations | `install.svc.plus` |
| `source_domain_base` | Source domain suffix | `svc.plus` |
| `target_domain_base` | Target domain suffix | `onwalk.net` |
| `observability_endpoint` | Telemetry gateway override | `https://observability.svc.plus` |
| `xray_exporter_image` | Optional immutable exporter image override | Empty uses the environment default. |
| `xconnect_gateway_ref` | UAT XConnect Gateway record key | `tw-xconnect.svc.plus` |
| `existing_target_host` | Existing-host deployment target | Empty; accepted only by its supported UAT route. |

The account form is unified as `cloud_account`; the resolver still accepts the old `akamai_account` field from existing internal callers during transition. The Agent controller URL is resolved from the selected environment contract. Vault uses the public `https://vault.svc.plus` endpoint and is not caller-configurable.

## PROD plan request

The current non-mutating PROD validation request is:

```text
source_ref=main
operation=plan
vault_env_path=prod-v6
target_domains=web-saas
cloud_provider=akamai-cloud
cloud_account=manbuzhe2026
instance_plan=2C4G
dns_mode=none
include_external_agent_proxy=false
skip_stripe_catalog=true
```

This request only validates and plans. It does not authorize IaC apply, application deployment, migration, or DNS changes.
