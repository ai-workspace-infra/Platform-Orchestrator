#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "json"

mode = ARGV.fetch(0)
if mode == "enforce"
  raise "Daily candidate run is incomplete or failed" unless ENV.fetch("ACCEPTED", "false") == "true"
  exit 0
end

deploy = ENV.fetch("DEPLOY_REQUESTED") == "true"
results = {
  prepare: ENV.fetch("PREPARE_RESULT"),
  build: ENV.fetch("BUILD_RESULT"),
  gate: ENV.fetch("GATE_RESULT"),
  dispatch: ENV.fetch("DISPATCH_RESULT")
}
accepted = results[:prepare] == "success" && results[:build] == "success" && results[:gate] == "success"
accepted &&= results[:dispatch] == "success" if deploy
accepted &&= results[:dispatch] == "skipped" unless deploy
summary = {
  schema_version: 1,
  candidate_id: ENV.fetch("CANDIDATE_ID", ""),
  candidate_fingerprint: ENV.fetch("CANDIDATE_FINGERPRINT", ""),
  deploy_requested: deploy,
  results: results,
  accepted: accepted,
  statement: deploy ? "fixed candidate build and explicit UAT owner dispatch" : "fixed candidate build only"
}
directory = File.join(ENV.fetch("RUNNER_TEMP"), "daily-candidate-summary")
FileUtils.mkdir_p(directory)
path = File.join(directory, "summary.json")
File.write(path, "#{JSON.pretty_generate(summary)}\n")
File.open(ENV.fetch("GITHUB_STEP_SUMMARY"), "a") do |file|
  file.puts("## Daily candidate")
  file.puts
  file.puts("- Candidate: `#{summary[:candidate_id]}`")
  file.puts("- Fingerprint: `#{summary[:candidate_fingerprint]}`")
  file.puts("- Scope: #{summary[:statement]}")
  results.each { |stage, result| file.puts("- #{stage}: `#{result}`") }
  file.puts("- Final: **#{accepted ? 'accepted' : 'rejected'}**")
end
File.open(ENV.fetch("GITHUB_OUTPUT"), "a") do |file|
  file.puts("summary_path=#{path}")
  file.puts("accepted=#{accepted}")
end

