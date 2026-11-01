import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const API = process.env.GITHUB_API_URL || "https://api.github.com";

function b64(value) { return Buffer.from(value).toString("base64url"); }
function jwt(clientId, privateKey) {
  const now = Math.floor(Date.now() / 1000);
  const unsigned = `${b64(JSON.stringify({ alg: "RS256", typ: "JWT" }))}.${b64(JSON.stringify({ iat: now - 60, exp: now + 540, iss: clientId }))}`;
  return `${unsigned}.${crypto.sign("RSA-SHA256", Buffer.from(unsigned), privateKey).toString("base64url")}`;
}
async function api(route, { token, method = "GET", body, raw = false } = {}) {
  const response = await fetch(`${API}${route}`, {
    method,
    headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`GitHub API ${method} ${route} failed (${response.status})`);
  if (raw) return Buffer.from(await response.arrayBuffer());
  return response.status === 204 ? null : response.json();
}
async function repoToken(repository) {
  const appToken = jwt(process.env.GITHUB_APP_CLIENT_ID, process.env.GITHUB_APP_PRIVATE_KEY);
  const installation = await api(`/repos/${repository}/installation`, { token: appToken });
  const created = await api(`/app/installations/${installation.id}/access_tokens`, {
    token: appToken, method: "POST", body: { repositories: [repository.split("/")[1]], permissions: { actions: "write", contents: "write" } },
  });
  return created.token;
}
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function output(name, value) { fs.appendFileSync(process.env.GITHUB_OUTPUT, `${name}=${String(value).replaceAll("\n", "%0A")}\n`); }
function findJsonReceipt(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      const nested = findJsonReceipt(candidate);
      if (nested) return nested;
    } else if (entry.isFile() && entry.name.endsWith(".json")) {
      return candidate;
    }
  }
  return null;
}

async function main() {
  const config = JSON.parse(process.env.UAT_DISPATCH_JSON || "{}");
  if (config.status !== "ready") throw new Error("UAT owner declaration is not ready");
  for (const key of ["owner_key", "owner_repository", "owner_workflow", "receipt_artifact", "target_ref"]) {
    if (!config[key]) throw new Error(`UAT owner declaration is missing ${key}`);
  }
  const manifest = JSON.parse(fs.readFileSync(process.env.CANDIDATE_MANIFEST, "utf8"));
  if (manifest.fingerprint !== process.env.CANDIDATE_FINGERPRINT) throw new Error("candidate fingerprint mismatch");
  const ownerSha = manifest.owners?.[`${config.owner_key}_sha`] || "";
  if (!/^[0-9a-f]{40}$/.test(ownerSha)) throw new Error("UAT owner key is not backed by a pinned candidate SHA");
  const token = await repoToken(config.owner_repository);
  const commit = await api(`/repos/${config.owner_repository}/commits/${ownerSha}`, { token });
  if (commit.sha !== ownerSha) throw new Error("UAT owner repository does not contain the pinned candidate SHA");
  const tag = `${manifest.candidate_id}-uat-owner`;
  const refRoute = `/repos/${config.owner_repository}/git/ref/tags/${encodeURIComponent(tag)}`;
  let existing = null;
  const probe = await fetch(`${API}${refRoute}`, { headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}` } });
  if (probe.status !== 404) {
    if (!probe.ok) throw new Error(`cannot inspect UAT owner tag (${probe.status})`);
    existing = await probe.json();
  }
  if (existing && existing.object.sha !== commit.sha) throw new Error("UAT owner tag points to a different SHA");
  if (!existing) await api(`/repos/${config.owner_repository}/git/refs`, { token, method: "POST", body: { ref: `refs/tags/${tag}`, sha: commit.sha } });
  const before = Date.now();
  await api(`/repos/${config.owner_repository}/actions/workflows/${encodeURIComponent(config.owner_workflow)}/dispatches`, {
    token,
    method: "POST",
    body: { ref: tag, inputs: { candidate_id: manifest.candidate_id, candidate_fingerprint: manifest.fingerprint, delivery_scope: manifest.delivery_scope, target_ref: config.target_ref } },
  });
  const timeout = Number.parseInt(process.env.UAT_OWNER_TIMEOUT_SECONDS || "3600", 10);
  let run = null;
  while ((Date.now() - before) / 1000 < timeout) {
    const data = await api(`/repos/${config.owner_repository}/actions/workflows/${encodeURIComponent(config.owner_workflow)}/runs?branch=${encodeURIComponent(tag)}&event=workflow_dispatch&per_page=20`, { token });
    run = data.workflow_runs.filter((entry) => entry.head_sha === commit.sha && Date.parse(entry.created_at) >= before - 5000).sort((a, b) => b.id - a.id)[0] || null;
    if (!run || run.status !== "completed") { await sleep(10000); continue; }
    if (run.conclusion !== "success") throw new Error(`UAT owner run ${run.html_url} concluded ${run.conclusion}`);
    break;
  }
  if (!run || run.status !== "completed") throw new Error("timed out waiting for the UAT owner run");
  const artifacts = await api(`/repos/${config.owner_repository}/actions/runs/${run.id}/artifacts`, { token });
  const receiptArtifact = artifacts.artifacts.find((artifact) => artifact.name === config.receipt_artifact && !artifact.expired);
  if (!receiptArtifact) throw new Error("declared UAT receipt artifact is missing");
  const archive = await api(`/repos/${config.owner_repository}/actions/artifacts/${receiptArtifact.id}/zip`, { token, raw: true });
  const directory = fs.mkdtempSync(path.join(process.env.RUNNER_TEMP, "uat-owner-receipt-"));
  const zip = path.join(directory, "receipt.zip");
  fs.writeFileSync(zip, archive, { mode: 0o600 });
  execFileSync("unzip", ["-qq", zip, "-d", directory]);
  const receiptPath = findJsonReceipt(directory);
  if (!receiptPath) throw new Error("UAT receipt artifact contains no JSON receipt");
  const receipt = JSON.parse(fs.readFileSync(receiptPath, "utf8"));
  if (receipt.candidate_id !== manifest.candidate_id || receipt.candidate_fingerprint !== manifest.fingerprint || receipt.status !== "success") {
    throw new Error("UAT owner receipt does not match the fixed candidate");
  }
  output("receipt_path", receiptPath);
  output("run_id", run.id);
  output("run_attempt", run.run_attempt);
}

main().catch((error) => { console.error(`::error::${error.message}`); process.exitCode = 1; });

