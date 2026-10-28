#!/usr/bin/env python3
"""Synthetic contract falsification only; not live referral/Sandbox acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('feature_gate', ROOT / '.github/scripts/feature-lane/gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class FeatureTagTests(unittest.TestCase):
    def test_tag_is_bound_to_complete_feature_id(self):
        self.assertEqual(gate.validate_feature_tag('smoke-sit-test-1483', 'sit-test-1483'), 'smoke')
        for tag in ('sit-test-1483', 'smoke-sit-test-1484', 'smoke--sit-test-1483', 'Smoke-sit-test-1483'):
            with self.subTest(tag=tag), self.assertRaises(gate.Blocked):
                gate.validate_feature_tag(tag, 'sit-test-1483')

    def test_candidate_domain_is_bound_to_full_tag(self):
        candidate, policy, *_ = fixture()
        candidate['schema'] = 2
        candidate['feature_tag'] = 'smoke-' + candidate['feature_id']
        candidate['domains']['sit'] = candidate['feature_tag'] + '-sit.' + policy['domain_suffix']
        gate.validate_candidate(candidate, policy)
        candidate['domains']['sit'] = 'other-' + candidate['domains']['sit']
        with self.assertRaisesRegex(gate.Blocked, 'unapproved temporary SIT domain'):
            gate.validate_candidate(candidate, policy)

    def test_service_hostname_lengths_are_validated_before_acceptance(self):
        candidate, policy, *_ = fixture()
        candidate['schema'] = 2
        candidate['feature_tag'] = 'a' * 40 + '-' + candidate['feature_id']
        candidate['domains']['sit'] = candidate['feature_tag'] + '-sit.' + policy['domain_suffix']
        with self.assertRaisesRegex(gate.Blocked, 'DNS label exceeds'):
            gate.validate_candidate(candidate, policy)

    def test_main_rehearsal_requires_task_allowlist_and_baselines(self):
        candidate, policy, *_ = fixture()
        candidate.update(schema=2, feature_tag='smoke-' + candidate['feature_id'], candidate_mode='main-rehearsal')
        candidate['domains']['sit'] = candidate['feature_tag'] + '-sit.' + policy['domain_suffix']
        candidate['sources'][0].update(kind='baseline', pr=None)
        with self.assertRaisesRegex(gate.Blocked, 'explicitly allowed'):
            gate.validate_candidate(candidate, policy)
        policy['main_rehearsal_tasks'] = [candidate['task_url']]
        gate.validate_candidate(candidate, policy)
        candidate['candidate_mode'] = 'feature'
        with self.assertRaisesRegex(gate.Blocked, 'baseline alone'):
            gate.validate_candidate(candidate, policy)


def fixture():
    policy = {'target': 'dev-fixture', 'domain_suffix': 'test.invalid',
              'uat_target': {'namespace': 'web-saas-uat', 'domain': 'console-uat.test.invalid'},
              'repositories': ['example/accounts'], 'required_tests': ['rootless', 'ddl_refused', 'stripe_real'],
              'acceptance_owner': {'repository': 'example/playbooks', 'workflow': 'acceptance.yml', 'sha': 'c' * 40},
              'approvers': ['human'], 'authorization_url_prefix': 'https://github.com/example/control/issues/1#'}
    c = {'schema': 1, 'feature_id': 'xconnect-referral', 'environment': 'dev', 'target': 'dev-fixture',
         'task_url': 'https://github.com/example/accounts/issues/1',
         'namespaces': {'sit': 'feature-xconnect-referral-sit', 'uat': 'web-saas-uat'},
         'domains': {'sit': 'xconnect-referral-sit.test.invalid', 'uat': 'console-uat.test.invalid'},
         'chart_digest': 'sha256:' + 'a' * 64, 'config_sha256': 'b' * 64, 'data_baseline_sha256': 'd' * 64,
         'required_tests': policy['required_tests'],
         'sources': [{'repository': 'example/accounts', 'kind': 'feature', 'pr': 2,
                      'sha': 'a' * 40, 'image': 'registry.invalid/accounts@sha256:' + 'a' * 64}]}
    prs = {'example/accounts': {'repository': 'example/accounts', 'number': 2, 'head_sha': 'a' * 40,
                              'base_ref': 'main', 'head_repository': 'example/accounts', 'state': 'OPEN', 'merged': False}}
    run = {'repository': 'example/playbooks', 'path': 'acceptance.yml', 'head_sha': 'c' * 40,
           'event': 'workflow_dispatch', 'id': 42, 'attempt': 1, 'status': 'completed', 'conclusion': 'success'}
    receipt = {'schema': 1, 'evidence_kind': 'live', 'run_id': 42, 'run_attempt': 1,
               'candidate_sha256': gate.identity(c), 'stage': 'sit', 'target': c['target'],
               'namespace': c['namespaces']['sit'], 'domain': c['domains']['sit'],
               'image_ids': {s['repository']: s['image'] for s in c['sources']},
               'tests': {t: 'PASS' for t in policy['required_tests']}, 'data_baseline_sha256': c['data_baseline_sha256'],
               'flux_ready': True, 'declaration_sha256': c['config_sha256']}
    auth = {'candidate_sha256': gate.identity(c), 'actor': 'human', 'decision': 'approved',
            'evidence_url': policy['authorization_url_prefix'] + 'issuecomment-42'}
    return c, policy, prs, receipt, run, auth


class GateTest(unittest.TestCase):
    def decide(self, values, stage='merge'):
        c, policy, prs, receipt, run, auth = values
        return gate.rehearse(c, policy, stage, prs, receipt, run, auth)

    def mark_merged(self, values):
        source = values[0]['sources'][0]
        values[2]['example/accounts'].update(merged=True, state='CLOSED', merge_sha='e' * 40,
            merge_artifact={'merge_sha': 'e' * 40, 'source_sha': source['sha'], 'image': source['image'],
                            'manifest_sha256': 'f' * 64, 'source_tree_sha': 'b' * 40, 'merge_tree_sha': 'b' * 40})

    def test_event_chain_keeps_execution_disabled_and_separate_namespaces(self):
        values = fixture()
        sit = self.decide(values, 'sit')
        merged = self.decide(values)
        self.mark_merged(values)
        uat = self.decide(values, 'uat')
        self.assertNotEqual(sit['namespace'], uat['namespace'])
        self.assertEqual(sit['candidate_sha256'], uat['candidate_sha256'])
        self.assertEqual(merged['execution'], 'NOT_RUN')
        self.assertFalse(uat['dispatch_authorized'])
        self.assertEqual(uat['status'], 'REHEARSAL')

    def test_merged_referral_cannot_pretend_to_be_premerge_sit(self):
        values = fixture()
        self.mark_merged(values)
        with self.assertRaises(gate.Blocked): self.decide(values, 'sit')
        values = fixture()
        values[0]['sources'][0].update(kind='baseline', pr=None)
        with self.assertRaises(gate.Blocked): self.decide(values, 'sit')

    def test_original_three_merged_referral_prs_are_baseline_only(self):
        c, policy, prs, receipt, run, auth = fixture()
        entries = [('ai-workspace-services/accounts', 277, '8d1b09a6f2022af221b2a817d516952af41ced0e'),
                   ('ai-workspace-services/portal', 472, '2a272f295235efdd39f469245ad74177d1a5ff5d'),
                   ('ai-workspace-services/frontend-router', 35, 'ab3f9e81223f19290b03a6b8d2dfefffb3309e55')]
        policy['repositories'] = [entry[0] for entry in entries]
        c['sources'] = [{'repository': repo, 'kind': 'baseline', 'pr': None, 'sha': commit,
                         'image': 'registry.invalid/' + repo.split('/')[-1] + '@sha256:' + 'a' * 64}
                        for repo, number, commit in entries]
        with self.assertRaisesRegex(gate.Blocked, 'already merged baseline'):
            gate.gate(c, policy, 'sit', {})
        for source, (repo, number, commit) in zip(c['sources'], entries):
            source.update(kind='feature', pr=number)
            prs[repo] = {'repository': repo, 'number': number, 'head_sha': commit, 'base_ref': 'main',
                         'head_repository': repo, 'state': 'CLOSED', 'merged': True, 'merge_sha': commit}
        with self.assertRaisesRegex(gate.Blocked, 'unmerged PR'):
            gate.gate(c, policy, 'sit', prs)

    def test_stale_or_untrusted_pr_rejected(self):
        for change in ({'head_sha': 'f' * 40}, {'head_repository': 'foreign/accounts'}, {'base_ref': 'release/v1'}):
            values = fixture(); values[2]['example/accounts'].update(change)
            with self.subTest(change=change), self.assertRaises(gate.Blocked): self.decide(values, 'sit')

    def test_missing_isolation_or_mutable_artifacts_rejected(self):
        mutations = [lambda c: c.update(target='prod'), lambda c: c.update(data_baseline_sha256='unknown'),
                     lambda c: c['namespaces'].update(uat=c['namespaces']['sit']),
                     lambda c: c['domains'].update(sit='prod.invalid'),
                     lambda c: c['sources'][0].update(image='registry.invalid/accounts:latest')]
        for mutation in mutations:
            values = fixture(); mutation(values[0])
            with self.subTest(mutation=mutation), self.assertRaises(gate.Blocked): self.decide(values, 'sit')

    def test_receipt_falsification_is_rejected(self):
        mutations = [lambda r: r.update(evidence_kind='mock'), lambda r: r.update(run_id=43),
                     lambda r: r.update(candidate_sha256='e' * 64), lambda r: r.update(flux_ready=False),
                     lambda r: r.update(image_ids={}), lambda r: r.update(namespace='uat'),
                     lambda r: r.update(data_baseline_sha256='f' * 64),
                     lambda r: r['tests'].update(stripe_real='BLOCKED'), lambda r: r['tests'].pop('ddl_refused')]
        for mutation in mutations:
            values = fixture(); mutation(values[3])
            with self.subTest(mutation=mutation), self.assertRaises(gate.Blocked): self.decide(values)

    def test_foreign_failed_or_mismatched_attempt_evidence_run_rejected(self):
        for change in ({'path': 'other.yml'}, {'head_sha': 'f' * 40}, {'event': 'pull_request'},
                       {'repository': 'foreign/playbooks'}, {'conclusion': 'failure'}, {'attempt': 2}):
            values = fixture(); values[4].update(change)
            with self.subTest(change=change), self.assertRaises(gate.Blocked): self.decide(values)

    def test_legitimate_rerun_with_exact_receipt_attempt_is_valid(self):
        values = fixture()
        values[4]['attempt'] = 3
        values[3]['run_attempt'] = 3
        self.assertEqual(self.decide(values)['status'], 'REHEARSAL')
        for bad in (None, 0, -1, True, '3'):
            values[4]['attempt'] = bad
            with self.subTest(attempt=bad), self.assertRaises(gate.Blocked): self.decide(values)

    def test_null_unknown_or_malformed_baseline_fields_are_blocked(self):
        for field in ('chart_digest', 'config_sha256', 'data_baseline_sha256'):
            for bad in (None, 'unknown', {}, 42):
                values = fixture(); values[0][field] = bad
                with self.subTest(field=field, value=bad), self.assertRaisesRegex(gate.Blocked, field):
                    self.decide(values, 'sit')

    def test_null_template_collections_and_identifiers_are_blocked(self):
        for field in ('namespaces', 'domains', 'required_tests', 'sources', 'feature_id', 'task_url'):
            values = fixture(); values[0][field] = None
            with self.subTest(field=field), self.assertRaises(gate.Blocked): self.decide(values, 'sit')

    def test_uat_uses_trusted_stable_target_not_feature_temporary_target(self):
        values = fixture(); self.mark_merged(values)
        result = self.decide(values, 'uat')
        self.assertEqual(result['namespace'], 'web-saas-uat')
        self.assertEqual(result['domain'], 'console-uat.test.invalid')
        for field, bad in (('namespaces', 'feature-xconnect-referral-uat'),
                           ('domains', 'xconnect-referral-uat.test.invalid')):
            changed = copy.deepcopy(values); changed[0][field]['uat'] = bad
            with self.subTest(field=field), self.assertRaisesRegex(gate.Blocked, 'trusted declared'):
                self.decide(changed, 'uat')

    def test_uat_requires_explicit_merge_artifact_and_tree_equivalence(self):
        values = fixture(); self.mark_merged(values)
        del values[2]['example/accounts']['merge_artifact']
        with self.assertRaisesRegex(gate.Blocked, 'merge SHA to artifact'): self.decide(values, 'uat')
        for change in ({'merge_sha': 'd' * 40}, {'source_sha': 'd' * 40}, {'image': 'other@sha256:' + 'f' * 64},
                       {'manifest_sha256': None}, {'source_tree_sha': None}, {'merge_tree_sha': 'd' * 40}):
            values = fixture(); self.mark_merged(values)
            values[2]['example/accounts']['merge_artifact'].update(change)
            with self.subTest(change=change), self.assertRaises(gate.Blocked): self.decide(values, 'uat')

    def test_human_authorization_required(self):
        for change in ({'actor': 'bot'}, {'decision': 'pending'}, {'candidate_sha256': 'f' * 64},
                       {'evidence_url': 'https://untrusted.invalid/approval'}):
            values = fixture(); values[5].update(change)
            with self.subTest(change=change), self.assertRaises(gate.Blocked): self.decide(values)

    def test_uat_requires_all_main_merges(self):
        with self.assertRaises(gate.Blocked): self.decide(fixture(), 'uat')

    def test_raw_json_or_approved_bool_cannot_authenticate_live_evidence(self):
        c, policy, prs, receipt, run, auth = fixture()
        for stage in ('merge', 'uat'):
            for approval in (auth, True, {'approved': True}):
                with self.subTest(stage=stage, approval=approval), self.assertRaisesRegex(gate.Blocked, 'retrieval adapter'):
                    gate.gate(c, policy, stage, prs, receipt, run, approval)
        result = gate.gate(c, policy, 'sit', prs)
        self.assertEqual(result['status'], 'PLAN_VALID')
        self.assertEqual(result['evidence_kind'], 'unverified_snapshot')

    def test_postmerge_artifact_change_invalidates_old_sit(self):
        values = fixture()
        self.mark_merged(values)
        values[0]['sources'][0]['image'] = 'registry.invalid/accounts@sha256:' + 'f' * 64
        with self.assertRaises(gate.Blocked): self.decide(values, 'uat')

    def configuration_fixture(self):
        values=fixture();c,policy,prs,receipt,run,auth=values
        c['sources'][0].update(kind='baseline',pr=None)
        c['components']={'accounts':{'source_repository':'example/accounts','image':c['sources'][0]['image']}}
        row={'repository':'example/config','pr':7,'sha':'7'*40,'base_ref':'main','base_sha':'6'*40,
             'paths':{'services/referral/values.yaml':'a'*64}}
        c['configurations']=[row];policy['runtime_components']={'accounts':'example/accounts'};policy['configuration_paths']={'example/config':['services/referral/']}
        snapshot={'repository':'example/config','number':7,'head_repository':'example/config','head_sha':row['sha'],
                  'base_ref':'main','base_sha':row['base_sha'],'state':'OPEN','merged':False,'path_hashes':row['paths'].copy()}
        receipt.update(candidate_sha256=gate.identity(c),image_ids={'accounts':c['sources'][0]['image']})
        auth['candidate_sha256']=gate.identity(c)
        return values,{'example/config#7':snapshot}

    def test_configuration_pr_can_test_merged_image_baselines_without_fake_app_pr(self):
        values,configs=self.configuration_fixture()
        c,policy,prs,receipt,run,auth=values
        result=gate.rehearse(c,policy,'merge',{},receipt,run,auth,config_prs=configs)
        self.assertEqual(result['status'],'REHEARSAL')
        self.assertEqual(c['sources'][0]['kind'],'baseline')
        receipt['image_ids']={'example/accounts':c['sources'][0]['image']}
        with self.assertRaisesRegex(gate.Blocked,'runtime image mismatch'):
            gate.rehearse(c,policy,'merge',{},receipt,run,auth,config_prs=configs)

    def test_configuration_paths_source_and_runtime_producer_are_not_weakened(self):
        for mutate in (lambda c,p:p['example/config#7'].update(head_sha='8'*40),
                       lambda c,p:p['example/config#7'].update(path_hashes={}),
                       lambda c,p:c['configurations'][0]['paths'].update({'other/file.yaml':'a'*64}),
                       lambda c,p:c['components'].update(postgresql={'source_repository':'missing/postgresql','image':'db@sha256:'+'a'*64})):
            values,configs=self.configuration_fixture();mutate(values[0],configs)
            with self.assertRaises(gate.Blocked):
                gate.rehearse(values[0],values[1],'sit',{},config_prs=configs)

    def test_configuration_uat_requires_identical_paths_on_merged_main(self):
        values,configs=self.configuration_fixture();snapshot=configs['example/config#7']
        snapshot.update(state='CLOSED',merged=True,merge_sha='9'*40,merged_path_hashes=snapshot['path_hashes'].copy())
        c,policy,prs,receipt,run,auth=values
        self.assertEqual(gate.rehearse(c,policy,'uat',{},receipt,run,auth,config_prs=configs)['namespace'],'web-saas-uat')
        snapshot['merged_path_hashes']={}
        with self.assertRaises(gate.Blocked):gate.rehearse(c,policy,'uat',{},receipt,run,auth,config_prs=configs)

    def test_configuration_stack_requires_exact_parent_and_cannot_claim_uat(self):
        values,configs=self.configuration_fixture();c,policy=values[:2]
        child=dict(c['configurations'][0],pr=8,sha='8'*40,base_ref='feature/parent',base_sha='7'*40,depends_on_pr=7)
        c['configurations'].append(child);c['configuration_entrypoint']='example/config#8'
        self.assertEqual(len(gate.configurations(c,policy)),2)
        child['base_sha']='9'*40
        with self.assertRaises(gate.Blocked):gate.configurations(c,policy)

    def test_real_referral_configuration_facts_are_expressible_unknowns_stay_blocked(self):
        real=json.loads((ROOT/'scripts/tests/control_plane/fixtures/xconnect-referral-declarations.json').read_text())
        policy={'configuration_paths':{'ai-workspace-infra/gitops':['services/distributed-web-saas-fullstack/feature-xconnect-referral-sit/']}}
        self.assertEqual(len(gate.configurations({'configurations':real['configurations'],'configuration_entrypoint':'ai-workspace-infra/gitops#602'},policy)),2)
        for row in real['configurations']:
            gate.verify_configuration(row,real['config_pr_snapshots'][row['repository']+'#'+str(row['pr'])],'sit')
        self.assertEqual(real['baseline_prs']['accounts']['pr'],277)
        self.assertFalse(real['external_router']['in_lane'])
        self.assertTrue(real['blockers'])
        self.assertEqual(real['evidence_kind'],'declaration_snapshot_not_live_acceptance')
        c,full_policy,*_=fixture()
        c.update(task_url=real['task']['url'],task_sha256=real['task']['sha256'],
                 configurations=real['configurations'],configuration_entrypoint=real['configuration_entrypoint'],
                 data_baseline_sha256=None)
        pairs=[('accounts','ai-workspace-services/accounts','accounts'),
               ('portal','ai-workspace-services/portal','console'),
               ('postgresql','ai-workspace-services/postgresql','postgresql')]
        c['sources']=[{'repository':repo,'kind':'baseline','pr':None,
                       'sha':real['baseline_prs'][name]['sha'] if name!='postgresql' else None,
                       'image':real['runtime_images'][component]} for name,repo,component in pairs]
        c['components']={component:{'source_repository':repo,'image':real['runtime_images'][component]} for name,repo,component in pairs}
        full_policy.update(configuration_paths=policy['configuration_paths'],repositories=[p[1] for p in pairs],
                           runtime_components={p[2]:p[1] for p in pairs})
        with self.assertRaisesRegex(gate.Blocked,'data_baseline_sha256'):gate.validate_candidate(c,full_policy)
        # A synthetic baseline only exposes the next real missing producer; it is not real evidence.
        c['data_baseline_sha256']='d'*64
        with self.assertRaisesRegex(gate.Blocked,'source must be full SHA'):gate.validate_candidate(c,full_policy)
        self.assertIsNone(real['postgresql_package']['producer_source_sha'])


    def test_any_config_change_invalidates_receipt(self):
        values = fixture(); values[0]['config_sha256'] = 'f' * 64
        with self.assertRaises(gate.Blocked): self.decide(values)


if __name__ == '__main__': unittest.main()
