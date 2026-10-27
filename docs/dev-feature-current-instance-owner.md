# Dev feature owner update after host recreation

The fixed SIT owner now accepts the instance selected by authenticated Dev CMDB, and binds namespace, node, cluster, candidate and seed receipts to it. The static reusable workflow reference is required by GitHub Actions and remains transitional until verified release-tag selection is implemented.

After the Playbooks owner is reviewed and before dispatch, apply only the new dev-feature-flux job_workflow_ref to the existing Dev Vault role; preserve the old approved callee and all existing claims/policies. The fresh live role must be compared first. This declaration does not modify Vault. A real successful prepare receipt and separate denied-path tests are still required.

CI's read-only integration qualification selects the current candidate and foundation via the non-secret repository variables `DEV_SIT_QUALIFY_PR`, `DEV_SIT_FOUNDATION_RUN`, `DEV_SIT_SUMMARY_ARTIFACT`, and `DEV_SIT_BOOTSTRAP_ARTIFACT`. Update these pointers after replacing the foundation or selecting another candidate. They are locators only: the verifier still authenticates the GitHub run, artifact checksums, all component publishers, current PR head, CMDB, node and cluster identity. Missing, stale, inaccessible or mismatched pointers fail closed. The qualification does not issue deployment authorization or execute changes.
