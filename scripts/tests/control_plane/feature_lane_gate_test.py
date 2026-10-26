#!/usr/bin/env python3
"""Synthetic contract falsification only; not live referral/Sandbox acceptance."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('feature_gate', ROOT / '.github/scripts/feature-lane/gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


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

    def test_any_config_change_invalidates_receipt(self):
        values = fixture(); values[0]['config_sha256'] = 'f' * 64
        with self.assertRaises(gate.Blocked): self.decide(values)


if __name__ == '__main__': unittest.main()
