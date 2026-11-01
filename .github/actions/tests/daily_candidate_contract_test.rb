# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"
require "tmpdir"
require "yaml"

ROOT = File.expand_path("../../..", __dir__)
WORKFLOW = File.join(ROOT, ".github/workflows/daily-main-snapshot.yaml")

class DailyCandidateContractTest < Minitest::Test
  EXPECTED_JOBS = %w[
    resolve-snapshot-tag
    snapshot
    snapshot-gate
    dispatch-environment
    snapshot-summary
  ].freeze

  def workflow
    @workflow ||= YAML.load_file(WORKFLOW)
  end

  def test_five_stage_chain_and_owner_actions
    assert_equal EXPECTED_JOBS, workflow.fetch("jobs").keys
    assert_nil workflow.dig("jobs", "resolve-snapshot-tag", "needs")
    assert_equal "resolve-snapshot-tag", workflow.dig("jobs", "snapshot", "needs")
    assert_equal %w[resolve-snapshot-tag snapshot], workflow.dig("jobs", "snapshot-gate", "needs")
    assert_equal %w[resolve-snapshot-tag snapshot-gate], workflow.dig("jobs", "dispatch-environment", "needs")
    assert_equal EXPECTED_JOBS.first(4), workflow.dig("jobs", "snapshot-summary", "needs")

    source = File.read(WORKFLOW)
    assert_includes source, "uses: ./artifacts/.github/actions/component-candidate"
    assert_includes source, "uses: ./.github/actions/candidate-gate"
    refute_match(%r{\.github/scripts/(snapshots|serverless)/}, source)
    refute_match(/serverless-orchestrator|selfhost-orchestrator/, source)
    refute_match(/refs\/tags\/v\*|production_eligible:\s*true/, source)
  end

  def test_candidate_gate_rejects_a_source_sha_mismatch
    Dir.mktmpdir do |directory|
      receipts = File.join(directory, "receipts")
      Dir.mkdir(receipts)
      expected_sha = "a" * 40
      receipt = {
        component: "accounts",
        candidate_id: "daily-build-2026.11.01-r1",
        owner_sha: "b" * 40,
        source_sha: "c" * 40,
        status: "build_succeeded",
        artifact_digest: "sha256:#{'d' * 64}",
        artifact_assets: []
      }
      File.write(File.join(receipts, "accounts.json"), JSON.generate(receipt))
      matrix = {
        include: [{
          name: "accounts",
          component: {
            name: "accounts",
            resolved_source_sha: expected_sha,
            artifact: { kind: "oci-image" }
          }
        }]
      }
      output = File.join(directory, "output")
      env = {
        "CANDIDATE_ID" => receipt.fetch(:candidate_id),
        "COMPONENT_MATRIX_JSON" => JSON.generate(matrix),
        "RECEIPTS_DIRECTORY" => receipts,
        "DELIVERY_SCOPE" => "web-saas",
        "GITOPS_SHA" => "e" * 40,
        "ARTIFACTS_SHA" => receipt.fetch(:owner_sha),
        "IAC_SHA" => "f" * 40,
        "PLAYBOOKS_SHA" => "1" * 40,
        "GITHUB_SHA" => "2" * 40,
        "GITHUB_REPOSITORY" => "ai-workspace-infra/Platform-Orchestrator",
        "GITHUB_RUN_ID" => "1",
        "GITHUB_RUN_ATTEMPT" => "1",
        "RUNNER_TEMP" => directory,
        "GITHUB_OUTPUT" => output
      }
      _stdout, stderr, status = Open3.capture3(env, "ruby", File.join(ROOT, ".github/actions/candidate-gate/gate.rb"))
      refute status.success?
      assert_includes stderr, "source SHA mismatch for accounts"
    end
  end
end
