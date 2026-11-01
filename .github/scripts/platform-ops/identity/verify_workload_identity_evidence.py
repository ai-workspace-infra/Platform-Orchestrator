#!/usr/bin/env python3
"""Verify declared source-run evidence without accessing runtime credentials."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

matrix=module('matrix','.github/scripts/acceptance/migration_matrix.py')
provenance=module('provenance','.github/scripts/platform-ops/evidence/workflow_artifact_provenance.py')


def artifact_contract(row):
    return {'repository':row['repository'],'run_id':row['runId'],'attempt':row['attempt'],
            'workflow':row['workflow'],'event':row['event'],'ref':row['ref'],'commit':row['commit'],
            'artifact_id':row['artifactId'],'artifact_name':row['artifactName'],
            'artifact_digest':row['artifactDigest'],'filename':row['filename'],'file_sha256':row['fileSha256']}


def verify(spec, api=matrix.api, artifact_file=matrix.artifact_file):
    e=spec['evidence'];target=spec['target']; boot=e['bootstrap'];iac=e['iac']
    # Immutable tags must still resolve to their recorded commit; main provenance is verified against the run SHA.
    for row in (boot,iac):
        if row['ref'] != 'main' and api('repos/'+row['repository']+'/commits/'+row['ref']).get('sha') != row['commit']:
            raise ValueError('evidence ref no longer resolves to expected commit')
    raw_boot=provenance.verify_artifact(api,artifact_file,artifact_contract(boot))
    raw_iac=provenance.verify_artifact(api,artifact_file,artifact_contract(iac))
    inventory=provenance.verify_artifact(api,artifact_file,{**artifact_contract(iac),'filename':'inventory.json','file_sha256':iac['inventorySha256']})
    try:
        b=json.loads(raw_boot);summary=json.loads(raw_iac);c=summary['context']
        if (b['result']!='FLUX_HANDOVER_VERIFIED' or b['node']!=target['node']
                or b['version']!=target['kubernetesVersion'] or b['gitops_sha']!=boot['gitopsSha']
                or b['common']['result']!='COMMON_NODE_VERIFIED' or b['common']['node']!=target['node']
                or b['common']['os_identities']!='OS_IDENTITY_CHECKS_PASSED'):
            raise ValueError('bootstrap receipt does not satisfy identity prerequisites')
        if (summary['result']!='applied_verified' or c['action']!='apply' or c['environment']!=spec['environment']
                or c['gitops_sha']!=boot['gitopsSha'] or c['iac_sha']!=iac['iacSha']
                or str(c['run_id'])!=str(iac['runId']) or str(c['run_attempt'])!=str(iac['attempt'])
                or c['correlation_id']!=iac['correlationId']
                or target['iacTargetManifest'] not in c['declaration_files']):
            raise ValueError('IaC summary does not match target and bootstrap')
        matches=[t for t in c['targets'] if t['environment']==spec['environment'] and t['provider']==target['provider'] and t['account']==target['account'] and t['stages']['resources']['manifest']==target['declaration']]
        if len(matches)!=1:
            raise ValueError('IaC selected target does not match identity declaration')
        data=json.loads(inventory)
        matching=[v[target['node']] for v in data.values() if isinstance(v,dict) and target['node'] in v]
        if len(matching)!=1 or str(matching[0]['instance_id'])!=str(b['common']['cmdb_instance_id']):
            raise ValueError('inventory and bootstrap instance differ')
    except (KeyError,TypeError,json.JSONDecodeError):
        raise ValueError('invalid identity evidence') from None
    return {'bootstrap':raw_boot,'summary':raw_iac,'inventory':inventory,
            'bootstrap_sha256':hashlib.sha256(raw_boot).hexdigest(),'summary_sha256':hashlib.sha256(raw_iac).hexdigest(),
            'iac_catalog_manifest': c['manifest_path']}
