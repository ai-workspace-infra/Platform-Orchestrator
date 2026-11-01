#!/usr/bin/env ruby
# frozen_string_literal: true

require "base64"
require "json"
require "net/http"
require "openssl"
require "time"
require "uri"
require "yaml"

def require_env(name)
  value = ENV.fetch(name, "").strip
  raise "#{name} is required" if value.empty?
  value
end

def repository_sha(root)
  sha = IO.popen(["git", "-C", root, "rev-parse", "HEAD"], &:read).strip
  raise "invalid repository SHA for #{root}" unless sha.match?(/\A[0-9a-f]{40}\z/)
  sha
end

def base64url(value)
  Base64.urlsafe_encode64(value, padding: false)
end

def app_jwt(client_id, private_key)
  now = Time.now.to_i
  header = base64url(JSON.generate(alg: "RS256", typ: "JWT"))
  payload = base64url(JSON.generate(iat: now - 60, exp: now + 540, iss: client_id))
  unsigned = "#{header}.#{payload}"
  signature = OpenSSL::PKey::RSA.new(private_key).sign(OpenSSL::Digest::SHA256.new, unsigned)
  "#{unsigned}.#{base64url(signature)}"
end

def github(path, token:, method: :get, body: nil, allow_not_found: false)
  uri = URI("#{ENV.fetch('GITHUB_API_URL', 'https://api.github.com')}#{path}")
  request = method == :post ? Net::HTTP::Post.new(uri) : Net::HTTP::Get.new(uri)
  request["Accept"] = "application/vnd.github+json"
  request["Authorization"] = "Bearer #{token}"
  request["X-GitHub-Api-Version"] = "2022-11-28"
  if body
    request["Content-Type"] = "application/json"
    request.body = JSON.generate(body)
  end
  response = Net::HTTP.start(uri.host, uri.port, use_ssl: true) { |http| http.request(request) }
  return nil if allow_not_found && response.code.to_i == 404
  raise "GitHub API #{method.to_s.upcase} #{path} failed (#{response.code})" unless response.code.to_i.between?(200, 299)
  response.body.to_s.empty? ? nil : JSON.parse(response.body)
end

def repository_token(repository, client_id, private_key)
  jwt = app_jwt(client_id, private_key)
  installation = github("/repos/#{repository}/installation", token: jwt)
  name = repository.split("/", 2).last
  created = github(
    "/app/installations/#{installation.fetch('id')}/access_tokens",
    token: jwt,
    method: :post,
    body: { repositories: [name], permissions: { contents: "read" } }
  )
  created.fetch("token")
end

def tag_exists?(repository, candidate, token)
  !github("/repos/#{repository}/git/ref/tags/#{URI.encode_www_form_component(candidate)}", token: token, allow_not_found: true).nil?
end

def resolve_source_sha(repository, source_ref, token)
  commit = github("/repos/#{repository}/commits/#{URI.encode_www_form_component(source_ref)}", token: token)
  sha = commit.fetch("sha")
  raise "invalid source SHA for #{repository}" unless sha.match?(/\A[0-9a-f]{40}\z/)
  sha
end

def write_output(name, value)
  File.open(ENV.fetch("GITHUB_OUTPUT"), "a") { |file| file.puts("#{name}=#{value.to_s.gsub("\n", '%0A')}") }
end

gitops_root = require_env("GITOPS_ROOT")
artifacts_root = require_env("ARTIFACTS_ROOT")
iac_root = require_env("IAC_ROOT")
playbooks_root = require_env("PLAYBOOKS_ROOT")
scope = require_env("SELECTED_DELIVERY_SCOPE")
raise "delivery_scope is invalid" unless scope.match?(/\A[a-z0-9][a-z0-9-]*\z/)
expected_policy_path = "delivery/candidates/#{scope}-uat.yaml"
raise "candidate policy path must be #{expected_policy_path}" unless require_env("CANDIDATE_POLICY_PATH") == expected_policy_path
policy_path = File.join(gitops_root, expected_policy_path)
policy = YAML.safe_load_file(policy_path, aliases: false)
raise "unsupported candidate policy" unless policy["kind"] == "ArtifactCandidatePolicy"
spec = policy.fetch("spec")
source_ref = require_env("SELECTED_SOURCE_REF")
raise "Daily candidate source_ref must match the reviewed policy" unless source_ref == spec.fetch("source_ref")
raise "delivery_scope does not match the reviewed policy" unless scope == spec.fetch("delivery_scope")
candidate_policy = spec.fetch("candidate")
raise "Daily cannot create a production-eligible candidate" unless candidate_policy["immutable"] == true && candidate_policy["production_eligible"] == false

components = spec.fetch("components")
raise "candidate policy has no components" if components.empty?
repositories = components.map { |component| component.fetch("source").fetch("repository") }.uniq
client_id = require_env("GITHUB_APP_CLIENT_ID")
private_key = require_env("GITHUB_APP_PRIVATE_KEY")
tokens = repositories.to_h { |repository| [repository, repository_token(repository, client_id, private_key)] }
resolved_source_shas = repositories.to_h do |repository|
  [repository, resolve_source_sha(repository, source_ref, tokens.fetch(repository))]
end
resolved_components = components.map do |component|
  source = component.fetch("source")
  component.merge("resolved_source_sha" => resolved_source_shas.fetch(source.fetch("repository")))
end

requested = ENV.fetch("REQUESTED_SNAPSHOT_TAG", "").strip
prefix = candidate_policy.fetch("id_prefix")
date = Time.now.utc.strftime("%Y.%m.%d")
if requested.empty?
  revision = 1
  loop do
    candidate = "#{prefix}-#{date}-r#{revision}"
    break requested = candidate unless repositories.any? { |repository| tag_exists?(repository, candidate, tokens.fetch(repository)) }
    revision += 1
  end
else
  pattern = /\A#{Regexp.escape(prefix)}-\d{4}\.\d{2}\.\d{2}-r[1-9]\d*\z/
  raise "snapshot_tag must be an immutable UAT Daily candidate" unless requested.match?(pattern)
  occupied = repositories.select { |repository| tag_exists?(repository, requested, tokens.fetch(repository)) }
  raise "snapshot_tag is already occupied in: #{occupied.join(', ')}" unless occupied.empty?
end

dispatch = spec.fetch("uat_dispatch")
deploy = require_env("DEPLOY_AFTER_BUILD") == "true"
target_ref = ENV.fetch("SELECTED_TARGET_REF", "").strip
if deploy
  raise "UAT dispatch owner is not ready in GitOps" unless dispatch.fetch("status") == "ready"
  raise "target_ref is required for explicit UAT dispatch" if target_ref.empty?
  raise "target_ref does not match the reviewed GitOps target" unless target_ref == dispatch.fetch("target_ref")
end

matrix = { include: resolved_components.map { |component| { name: component.fetch("name"), component: component } } }
write_output("candidate_id", requested)
write_output("component_matrix", JSON.generate(matrix))
write_output("gitops_sha", repository_sha(gitops_root))
write_output("artifacts_sha", repository_sha(artifacts_root))
write_output("iac_sha", repository_sha(iac_root))
write_output("playbooks_sha", repository_sha(playbooks_root))
write_output("uat_dispatch", JSON.generate(dispatch))

