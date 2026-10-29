#!/usr/bin/env python3
"""Authenticate a tag workflow event on Main before any privileged work."""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys


def load_trusted():
    spec = importlib.util.spec_from_file_location('feature_trusted', Path(__file__).with_name('trusted.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def installation_repositories(candidate, policy, binding):
    """Resolve the bounded repository set after tag and policy authentication."""
    match = re.fullmatch(r'https://github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/[1-9][0-9]*', candidate['task_url'])
    if not match or match.group(1) not in policy.get('task_repositories', []):
        raise ValueError('issue repository is outside reviewed policy')
    gitops = candidate.get('gitops', {}).get('repository')
    if gitops != policy.get('gitops_repository'):
        raise ValueError('GitOps repository differs from policy')
    repositories = {match.group(1), binding['repository'], gitops}
    repositories.update(row['repository'] for row in candidate['sources'])
    repositories.update(row['repository'] for row in candidate.get('configurations', []))
    canonical = policy.get('website_content_canonical_repository')
    if not isinstance(canonical, str) or not re.fullmatch(r'ai-workspace-services/[A-Za-z0-9_.-]+', canonical):
        raise ValueError('reviewed canonical content repository required')
    repositories.add(canonical)
    result = {'ai-workspace-infra': set(), 'ai-workspace-services': set()}
    for repository in repositories:
        parts = repository.split('/') if isinstance(repository, str) else []
        if (len(parts) != 2 or parts[0] not in result or
                not re.fullmatch(r'[A-Za-z0-9_.-]+', parts[1]) or parts[1] in ('.', '..')):
            raise ValueError('repository outside approved installations')
        result[parts[0]].add(parts[1])
    if any(not names or len(names) > 50 for names in result.values()):
        raise ValueError('missing or oversized installation scope')
    return {owner: sorted(names, key=str.lower) for owner, names in result.items()}


def authenticate(event, env, trusted):
    repo = env.get('GITHUB_REPOSITORY', '')
    if repo.lower() not in ('ai-workspace-infra/platform-orchestrator', 'ai-workspace-infra/platform-ops-toolkit'):
        raise ValueError('unapproved repository')
    if env.get('GITHUB_EVENT_NAME') != 'workflow_run' or env.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('trusted Main workflow event required')
    event_run = event.get('workflow_run', {})
    run_id = event_run.get('id')
    if event.get('action') != 'completed' or type(run_id) is not int or run_id <= 0:
        raise ValueError('completed source run required')
    run = trusted.reader.api(f'repos/{repo}/actions/runs/{run_id}')
    workflow = trusted.reader.api(f'repos/{repo}/actions/workflows/feature-tag-preflight.yml')
    tag = run.get('head_branch')
    if (type(workflow.get('id')) is not int or workflow['id'] <= 0 or
            type(event_run.get('run_attempt')) is not int or event_run['run_attempt'] <= 0 or
            run.get('run_attempt') != event_run['run_attempt'] or
            run.get('id') != run_id or run.get('workflow_id') != workflow.get('id') or
            run.get('path', '').split('@')[0] != '.github/workflows/feature-tag-preflight.yml' or
            run.get('event') != 'push' or run.get('status') != 'completed' or
            run.get('repository', {}).get('full_name', '').lower() != repo.lower() or
            run.get('head_repository', {}).get('full_name', '').lower() != repo.lower() or
            not isinstance(run.get('head_sha'), str) or not re.fullmatch(r'[0-9a-f]{40}', run['head_sha']) or
            not isinstance(tag, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+', tag) or len(tag) > 59):
        raise ValueError('source workflow event identity mismatch')
    # The source workflow is evaluated at the pushed ref. A branch with the
    # same name as a tag must not be able to substitute a branch-triggered
    # workflow. Require the reviewed Main workflow blob at the tag target.
    path = '.github/workflows/feature-tag-preflight.yml'
    source_file = trusted.reader.api(f'repos/{repo}/contents/{path}?ref={run["head_sha"]}')
    main_file = trusted.reader.api(f'repos/{repo}/contents/{path}?ref={env["GITHUB_SHA"]}')
    if (source_file.get('type') != 'file' or main_file.get('type') != 'file' or
            source_file.get('path') != path or main_file.get('path') != path or
            not re.fullmatch(r'[0-9a-f]{40}', str(source_file.get('sha', ''))) or
            source_file.get('sha') != main_file.get('sha')):
        raise ValueError('source workflow differs from reviewed Main')
    workspace = Path(env['GITHUB_WORKSPACE'])
    candidate_path = workspace / '.github' / 'feature-candidates' / tag / 'candidate.json'
    if candidate_path.is_symlink() or candidate_path.parent.is_symlink() or not candidate_path.is_file() or candidate_path.stat().st_size > 1_000_000:
        raise ValueError('reviewed candidate unavailable')
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    if not isinstance(candidate, dict) or candidate.get('feature_tag') != tag:
        raise ValueError('source tag and candidate mismatch')
    policy = trusted.policy_at(env['GITHUB_SHA'])
    binding = trusted.verify_feature_tag(candidate, policy)
    if binding['repository'].lower() != repo.lower() or binding['target_sha'] != run.get('head_sha'):
        raise ValueError('tag target differs from source event')
    trusted.gate.validate_candidate(candidate, policy)
    return tag, installation_repositories(candidate, policy, binding)


def main():
    try:
        env = os.environ
        event = json.loads(Path(env['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
        tag, repos = authenticate(event, env, load_trusted())
        with Path(env['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
            output.write(f'tag={tag}\n')
            for owner, key in (('ai-workspace-infra', 'infra_repositories'), ('ai-workspace-services', 'services_repositories')):
                output.write(f'{key}<<FEATURE_REPOSITORIES\n' + '\n'.join(repos[owner]) + '\nFEATURE_REPOSITORIES\n')
        return 0
    except Exception:
        print('::error::Feature event cannot be authenticated against reviewed Main policy', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
