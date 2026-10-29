"""Fail-closed terminal control receipt, with no resource execution."""
import json
import os


def classify(needs, operation):
    expected={'v6-resolve','v6-iac','v6-bootstrap'}
    if set(needs)!=expected or operation not in {'plan','infra','deploy'}:
        return 'preflight_failed', False
    if needs['v6-resolve']['result']!='success':
        return 'preflight_failed', False
    if needs['v6-iac']['result']!='success':
        return 'failed_inspect_iac_mutation_state', False
    if operation in {'infra','deploy'}:
        if needs['v6-bootstrap']['result']!='success':
            return 'mutated_and_failed', False
        return ('verified_paused_bootstrap' if operation=='deploy' else 'verified_infrastructure_and_common'), True
    if needs['v6-bootstrap']['result']!='skipped':
        return 'unexpected_bootstrap_execution', False
    return ('verified_plan' if operation=='plan' else 'verified_infrastructure'), True


def main():
    result,ok=classify(json.loads(os.environ['V6_NEEDS_JSON']),os.environ['V6_OPERATION'])
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as out:
        out.write('PROD-K3S-V6: '+result+'\n\nNo data migration, DNS or writer handoff.\n')
    if not ok:raise SystemExit(1)


if __name__=='__main__':main()
