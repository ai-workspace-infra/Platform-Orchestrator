#!/usr/bin/env ruby
# frozen_string_literal: true

require "digest"
require "fileutils"
require "json"

def require_env(name)
  value = ENV.fetch(name, "").strip
  raise "#{name} is required" if value.empty?
  value
end

def write_output(name, value)
  File.open(ENV.fetch("GITHUB_OUTPUT"), "a") { |file| file.puts("#{name}=#{value}") }
end

candidate_id = require_env("CANDIDATE_ID")
matrix = JSON.parse(require_env("COMPONENT_MATRIX_JSON"))
expected = matrix.fetch("include").to_h { |entry| [entry.fetch("name"), entry.fetch("component")] }
receipt_paths = Dir.glob(File.join(require_env("RECEIPTS_DIRECTORY"), "**", "*.json"))
receipts = receipt_paths.map { |path| JSON.parse(File.read(path)) }
actual_names = receipts.map { |receipt| receipt.fetch("component") }
raise "duplicate component receipts" unless actual_names.uniq.length == actual_names.length
missing = expected.keys - actual_names
unexpected = actual_names - expected.keys
raise "missing component receipts: #{missing.join(', ')}" unless missing.empty?
raise "unexpected component receipts: #{unexpected.join(', ')}" unless unexpected.empty?

receipts.each do |receipt|
  component = expected.fetch(receipt.fetch("component"))
  raise "candidate mismatch for #{receipt['component']}" unless receipt.fetch("candidate_id") == candidate_id
  raise "owner SHA mismatch for #{receipt['component']}" unless receipt.fetch("owner_sha") == require_env("ARTIFACTS_SHA")
  raise "source SHA mismatch for #{receipt['component']}" unless receipt.fetch("source_sha") == component.fetch("resolved_source_sha")
  raise "build failed for #{receipt['component']}" unless receipt.fetch("status") == "build_succeeded"
  artifact = component.fetch("artifact")
  case artifact.fetch("kind")
  when "oci-image"
    raise "missing OCI digest for #{receipt['component']}" unless receipt.fetch("artifact_digest", "").match?(/\Asha256:[0-9a-f]{64}\z/)
  when "github-release"
    required_assets = artifact.fetch("required_assets")
    missing_assets = required_assets - receipt.fetch("artifact_assets")
    raise "missing release assets for #{receipt['component']}: #{missing_assets.join(', ')}" unless missing_assets.empty?
  else
    raise "unsupported artifact kind for #{receipt['component']}"
  end
end

manifest = {
  schema_version: 1,
  candidate_id: candidate_id,
  environment: "uat",
  production_eligible: false,
  delivery_scope: require_env("DELIVERY_SCOPE"),
  owners: {
    orchestrator_sha: ENV.fetch("GITHUB_SHA"),
    gitops_sha: require_env("GITOPS_SHA"),
    artifacts_sha: require_env("ARTIFACTS_SHA"),
    iac_sha: require_env("IAC_SHA"),
    playbooks_sha: require_env("PLAYBOOKS_SHA")
  },
  build_run: {
    repository: ENV.fetch("GITHUB_REPOSITORY"),
    run_id: ENV.fetch("GITHUB_RUN_ID"),
    run_attempt: ENV.fetch("GITHUB_RUN_ATTEMPT")
  },
  components: receipts.sort_by { |receipt| receipt.fetch("component") }
}
fingerprint = Digest::SHA256.hexdigest(JSON.generate(manifest))
manifest[:fingerprint] = fingerprint
directory = File.join(ENV.fetch("RUNNER_TEMP"), "daily-candidate")
FileUtils.mkdir_p(directory)
path = File.join(directory, "candidate-manifest.json")
File.write(path, "#{JSON.pretty_generate(manifest)}\n")
write_output("manifest_path", path)
write_output("fingerprint", fingerprint)

