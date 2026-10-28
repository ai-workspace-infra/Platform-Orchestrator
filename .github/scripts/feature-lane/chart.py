#!/usr/bin/env python3
"""Authenticate the selected OCI chart against a Main build and source tree."""
import hashlib
import json
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = 'ai-workspace-infra/artifacts'
WORKFLOW = '.github/workflows/release-oci-charts.yml'
CHART_PATH = 'oci/charts/distributed-web-saas-fullstack'
SCRIPTS = ('.github/workflows/release-oci-charts.yml', '.github/scripts/release-oci-charts.sh',
           '.github/scripts/check-web-saas-charts.sh', '.github/scripts/web-saas-charts.sh')
OCI_REPO = 'ai-workspace-infra/distributed-web-saas-fullstack'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_bounded(opener, request, maximum):
    with opener.open(request, timeout=20) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('oversized registry response')
    return data


def registry_manifest(digest):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('invalid chart digest')
    opener = build_opener(NoRedirect())
    token_url = 'https://ghcr.io/token?service=ghcr.io&scope=repository%3Aai-workspace-infra%2Fdistributed-web-saas-fullstack%3Apull'
    token = json.loads(read_bounded(opener, Request(token_url), 16384)).get('token')
    if not isinstance(token, str) or not 1 <= len(token) <= 8192 or any(ord(c) < 32 for c in token):
        raise ValueError('invalid anonymous registry token')
    request = Request('https://ghcr.io/v2/' + OCI_REPO + '/manifests/' + digest,
                      headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.oci.image.manifest.v1+json'})
    raw = read_bounded(opener, request, 1_000_000)
    if 'sha256:' + hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('chart registry digest mismatch')
    return json.loads(raw)


def tree_at(reader, sha, path):
    commit = reader.api(f'repos/{REPO}/git/commits/{sha}')
    if commit.get('sha') != sha:
        raise ValueError('commit identity mismatch')
    tree_sha = commit.get('tree', {}).get('sha')
    for part in path.split('/'):
        if not re.fullmatch(r'[0-9a-f]{40}', str(tree_sha or '')):
            raise ValueError('missing tree identity')
        tree = reader.api(f'repos/{REPO}/git/trees/{tree_sha}')
        if tree.get('sha') != tree_sha or tree.get('truncated') is True or not isinstance(tree.get('tree'), list):
            raise ValueError('invalid tree listing')
        entries = [row for row in tree['tree'] if row.get('path') == part and row.get('type') == 'tree']
        if len(entries) != 1:
            raise ValueError('chart source tree unavailable')
        tree_sha = entries[0].get('sha')
    if not re.fullmatch(r'[0-9a-f]{40}', str(tree_sha or '')):
        raise ValueError('invalid chart source tree identity')
    return tree_sha


def verify(candidate, policy, selector, reader, file_at, registry=registry_manifest):
    owner = policy.get('chart_owner')
    if (not isinstance(owner, dict) or set(owner) != {'repository', 'workflow', 'package'} or
            owner.get('repository') != REPO or owner.get('workflow') != WORKFLOW or
            not re.fullmatch(r'distributed-web-saas-fullstack-[0-9]+\.[0-9]+\.[0-9]+\.tgz', str(owner.get('package', '')))):
        raise ValueError('unreviewed chart owner')
    if (not isinstance(selector, dict) or set(selector) != {'run_id', 'attempt', 'artifact_id'} or
            any(type(value) is not int or value <= 0 for value in selector.values())):
        raise ValueError('invalid chart evidence selector')
    rows = [source for source in candidate.get('sources', []) if source.get('repository') == REPO]
    if len(rows) != 1 or not re.fullmatch(r'[0-9a-f]{40}', str(rows[0].get('sha', ''))):
        raise ValueError('chart source Main identity missing')
    current_sha = rows[0]['sha']
    run_id, attempt, artifact_id = (selector[k] for k in ('run_id', 'attempt', 'artifact_id'))
    run = reader.api(f'repos/{REPO}/actions/runs/{run_id}')
    producer = run.get('head_sha')
    if (run.get('id') != run_id or run.get('run_attempt') != attempt or run.get('event') != 'push' or
            run.get('head_branch') != 'main' or run.get('path', '').split('@')[0] != WORKFLOW or
            run.get('status') != 'completed' or run.get('conclusion') != 'success' or
            run.get('repository', {}).get('full_name') != REPO or run.get('head_repository', {}).get('full_name') != REPO or
            not re.fullmatch(r'[0-9a-f]{40}', str(producer or ''))):
        raise ValueError('chart build provenance mismatch')
    comparison = reader.api(f'repos/{REPO}/compare/{producer}...{current_sha}')
    if comparison.get('status') not in ('ahead', 'identical'):
        raise ValueError('chart build source not ancestor of candidate')
    if tree_at(reader, producer, CHART_PATH) != tree_at(reader, current_sha, CHART_PATH):
        raise ValueError('chart source tree changed since build')
    for path in SCRIPTS:
        if file_at(REPO, producer, path) != file_at(REPO, current_sha, path):
            raise ValueError('chart build workflow or scripts changed')
    artifact_name = 'oci-charts-' + producer
    manifest_raw = reader.artifact_file(REPO, artifact_id, run_id, attempt, artifact_name, 'source-manifest.json', producer)
    package = reader.artifact_file(REPO, artifact_id, run_id, attempt, artifact_name, owner['package'], producer)
    manifest = json.loads(manifest_raw)
    package_sha = hashlib.sha256(package).hexdigest()
    if manifest.get('source_sha') != producer or manifest.get('packages', {}).get(owner['package']) != package_sha:
        raise ValueError('chart artifact manifest mismatch')
    oci = registry(candidate.get('chart_digest'))
    layers = oci.get('layers')
    if (oci.get('schemaVersion') != 2 or not isinstance(layers, list) or len(layers) != 1 or
            layers[0].get('mediaType') != 'application/vnd.cncf.helm.chart.content.v1.tar+gzip' or
            layers[0].get('digest') != 'sha256:' + package_sha or layers[0].get('size') != len(package)):
        raise ValueError('published chart differs from authenticated package')
    return {'build_run_id': run_id, 'build_attempt': attempt, 'artifact_id': artifact_id,
            'producer_sha': producer, 'candidate_source_sha': current_sha,
            'chart_digest': candidate['chart_digest'], 'package_sha256': package_sha}
