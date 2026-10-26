import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[3]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'.github/scripts/acceptance'/f'{name}.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


matrix=module('migration_matrix');gate=module('verify_report')


@pytest.fixture
def plan():
    target=dict(host='v5',host_id='123',machine_id='a'*32,known_hosts='example ssh-ed25519 synthetic-public-key',
                namespace='test',database_pod='pg-0',database_user='app',database_name='account',source_name='source',source_namespace='flux-system',schema='1',expected_agents=5)
    return dict(schema_version='v5-post-migration/v1',environment='uat',toolkit_sha='a'*40,gitops_sha='b'*40,iac_sha='c'*40,
                playbooks_sha='d'*40,infra_head_sha='e'*40,required_checks=[f'V5-{n:02}' for n in range(1,24)],
                cmdb_artifact_id='2',cmdb_artifact_name='cmdb',infra_run_id='3',infra_run_attempt='1',vault_addr='https://vault.example',targets=[target])


def test_absent_plan_does_not_enable_new_execution():
    assert matrix.validate_data_plan({},'uat','a'*40)==[]


def test_valid_plan_is_one_exact_target(plan):
    rows=matrix.validate_data_plan(dict(post_migration_v5=plan),'uat','a'*40)
    assert len(rows)==1 and rows[0]['plan']['target']['host_id']=='123'


@pytest.mark.parametrize('key,value',[('environment','prod'),('toolkit_sha','z'*40),('playbooks_sha','main'),('required_checks',[]),('targets',[]),('vault_addr','http://vault.example')])
def test_invalid_plan_never_enables_matrix(plan,key,value):
    plan[key]=value
    with pytest.raises(ValueError):matrix.validate_data_plan(dict(post_migration_v5=plan),'uat','a'*40)


def test_duplicate_hosts_rejected(plan):
    plan['targets']*=2
    with pytest.raises(ValueError):matrix.validate_data_plan(dict(post_migration_v5=plan),'uat','a'*40)


@pytest.fixture
def report_case(tmp_path,plan):
    row=matrix.validate_data_plan(dict(post_migration_v5=plan),'uat','a'*40)[0]
    data=dict(schema_version='v5-report/v1',execution_mode='ssh-playbook-role',environment='uat',owner_sha='d'*40,
              host_id='123',gitops_sha='b'*40,run_id='v5-10-2-v5',scope_verified=True,result='PASS',
              checks=[dict(id=f'V5-{n:02}',status='PASS') for n in range(1,24)])
    def save():
        (tmp_path/'evidence.json').write_text(json.dumps(data))
        (tmp_path/'report.zh.md').write_text('synthetic fixture, not runtime evidence')
        (tmp_path/'junit.xml').write_text('<testsuite tests="23" failures="0" errors="0" skipped="0">'+''.join(f'<testcase name="V5-{n:02}"/>' for n in range(1,24))+'</testsuite>')
        (tmp_path/'manifest.json').write_text(json.dumps({n:hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in ['evidence.json','report.zh.md','junit.xml']}))
    save()
    return tmp_path,row,data,save


def test_exact_report(report_case):
    root,row,data,save=report_case
    assert gate.validate(root,row,'10','2')


@pytest.mark.parametrize('key', ['environment','host_id','owner_sha','gitops_sha','run_id','schema_version'])
def test_wrong_report_identity(report_case,key):
    root,row,data,save=report_case;data[key]='wrong';save()
    with pytest.raises(ValueError):gate.validate(root,row,'10','2')


@pytest.mark.parametrize('status',['FAIL','SKIPPED','PARTIAL','NOT_RUN','UNKNOWN'])
def test_nonpass_report_cannot_release(report_case,status):
    root,row,data,save=report_case;data['checks'][0]['status']=status;save()
    with pytest.raises(ValueError):gate.validate(root,row,'10','2')


def test_tampered_report_rejected(report_case):
    root,row,data,save=report_case;(root/'evidence.json').write_text('{}')
    with pytest.raises(ValueError):gate.validate(root,row,'10','2')


def test_existing_workflow_has_one_new_owner_matrix_and_closed_verdict():
    data=yaml.load((ROOT/'.github/workflows/environment-data-operations.yml').read_text(),Loader=yaml.BaseLoader)
    job=data['jobs']['post_migration_v5']
    assert job['strategy']['fail-fast']=='false'
    assert any(s.get('uses')=='./playbooks/.github/actions/v5-readonly-acceptance' for s in job['steps'])
    assert any('verify_report.py' in s.get('run','') and s.get('if')=='${{ always() }}' for s in job['steps'])
    assert 'post_migration_v5' in data['jobs']['verdict']['needs']


@pytest.mark.parametrize('change',['expired','run','attempt','sha','digest','missing'])
def test_download_rejects_wrong_artifact_provenance(monkeypatch,change):
    import io
    import zipfile
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('other.json' if change=='missing' else 'cmdb.json','{}')
    raw=stream.getvalue()
    meta=dict(id=2,size_in_bytes=len(raw),expired=False,name='cmdb',workflow_run=dict(id=3),digest='sha256:'+hashlib.sha256(raw).hexdigest())
    run=dict(repository={'full_name':'org/repo'},run_attempt=1,head_sha='a'*40,status='completed',conclusion='success')
    if change=='expired':meta['expired']=True
    if change=='run':meta['workflow_run']['id']=4
    if change=='attempt':run['run_attempt']=2
    if change=='sha':run['head_sha']='b'*40
    if change=='digest':meta['digest']='sha256:'+'0'*64
    def api(path,binary=False):
        if binary:return raw
        if '/artifacts/' in path:return meta
        return run
    monkeypatch.setattr(matrix,'api',api)
    with pytest.raises(ValueError):matrix.artifact_file('org/repo','2','3','1','cmdb','cmdb.json','a'*40)


def test_contradictory_junit_rejected(report_case):
    root,row,data,save=report_case
    (root/'junit.xml').write_text('<testsuite tests="23" failures="0"/>')
    manifest=json.loads((root/'manifest.json').read_text())
    manifest['junit.xml']=hashlib.sha256((root/'junit.xml').read_bytes()).hexdigest()
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):gate.validate(root,row,'10','2')
