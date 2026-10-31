#!/usr/bin/env python3
"""Check explicit image and chart pins for a declared Kubernetes target."""
from pathlib import Path
import re
import sys
import yaml

DIGEST = re.compile(r'@sha256:[0-9a-f]{64}$')
OCI_DIGEST = re.compile(r'sha256:[0-9a-f]{64}$')


def inside(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_dir():
        raise ValueError('declared Flux path must be a directory inside GitOps')
    return path


def docs(directory):
    for path in directory.glob('*.yaml'):
        yield from (doc for doc in yaml.safe_load_all(path.read_text()) if isinstance(doc, dict))


def images(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'image' and isinstance(item, str):
                yield item
            elif key == 'image' and isinstance(item, dict) and 'tag' in item:
                yield str(item['tag'])
            else:
                yield from images(item)
    elif isinstance(value, list):
        for item in value:
            yield from images(item)


def validate(root_path, manifest_path):
    root = Path(root_path).resolve()
    manifest = Path(manifest_path).resolve()
    if not manifest.is_relative_to(root) or not manifest.is_file():
        raise ValueError('target manifest must be inside GitOps')
    hosts = yaml.safe_load(manifest.read_text()).get('hosts', [])
    if not hosts or any(host.get('host_vars', {}).get('deployment_mode') != 'kubernetes' for host in hosts):
        return False
    paths = {host['host_vars']['k3s_platform_flux_root_path'] for host in hosts}
    if len(paths) != 1:
        raise ValueError('all selected nodes must use the same Flux root')
    root_docs = list(docs(inside(root, paths.pop())))
    children = [item for item in root_docs if item.get('apiVersion', '').startswith('kustomize.toolkit.fluxcd.io/') and item.get('kind') == 'Kustomization']
    count_charts = count_images = 0
    for child in children:
        unit_docs = list(docs(inside(root, child['spec']['path'])))
        oci_names = {(item.get('metadata', {}).get('namespace'), item.get('metadata', {}).get('name')) for item in unit_docs if item.get('kind') == 'OCIRepository'}
        for item in unit_docs:
            spec = item.get('spec', {})
            if item.get('kind') == 'OCIRepository':
                if not OCI_DIGEST.fullmatch(spec.get('ref', {}).get('digest', '')):
                    raise ValueError('OCI charts require an immutable digest')
                count_charts += 1
            elif item.get('kind') == 'HelmRelease':
                chart = spec.get('chart', {}).get('spec', {})
                chart_ref = spec.get('chartRef', {})
                if not chart and (chart_ref.get('kind') != 'OCIRepository' or (chart_ref.get('namespace', item.get('metadata', {}).get('namespace')), chart_ref.get('name')) not in oci_names):
                    raise ValueError('HelmRelease must reference a declared OCI chart or a versioned chart')
                if chart:
                    if not re.fullmatch(r'v?[0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?', str(chart.get('version', ''))):
                        raise ValueError('Helm chart requires a fixed version')
                    count_charts += 1
                for image in images(spec.get('values', {})):
                    if not DIGEST.search(image):
                        raise ValueError('explicit workload image requires a digest')
                    count_images += 1
    if not count_charts or not count_images:
        raise ValueError('no pinned chart or image declarations found')
    return True


if __name__ == '__main__':
    try:
        print('true' if validate(*sys.argv[1:]) else 'false')
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise SystemExit(f'GitOps artifact validation failed: {exc}')
