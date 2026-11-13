# Civo release — 13 November 2026

AutoKaggle PRs #19, #20, and the evaluator-quality follow-up #21 are merged. Both services use main commit `404acb60fa679e03a8e3dbea7985fc67a6f92646`.

Source SHA-256: `e985108f5972a6b50e15393a2b26738aa078fcb0d7d12449783a9fc76b3bd820`.

- Full: `source-e985108f5972a6b5` in deployment `web`.
- Lite: `lite-source-e985108f5972a6b5` in deployment `lite`.
- Namespace: `autokaggle-web`; existing AutoKaggle Civo cluster in London.
- Provider: DeepSeek V4 Pro. Existing credentials, data volumes, access policy, builder image, and automatic publication settings were retained.

Before restart, the rollout found no active build jobs and made private SQLite backups on the existing volumes. Backup and current database integrity checks passed. All 35 original Full project bodies and all 11 original Lite project bodies remained unchanged. A separate Lite smoke-test session was then created through the interface.

The combined release passed 103 Python tests, with one skipped, and 68 interface tests. Both HTTPS services and anonymous admin denial passed. The live Lite browser test used short replies, displayed the owning-project question, and received a real DeepSeek proposal while keeping the missing project unresolved. The Full browser session reopened the agent and its saved checklist.

The BOLD OS receiver remains unconfigured. BOLD OS PR #31 stays open for Eduardo's review. No BOLD OS code was merged or deployed. The new OS agent tools are separate work and are not in this production bundle.

## Source rollback

Restore only the matching source ConfigMap and source-hash annotation. Keep current data and Secrets. Do not restore an old database as part of a source rollback.

- Previous Full source: `source-c909b1150ecd43a9`, SHA-256 `c909b1150ecd43a9511408c2f60b2003400a8bb706d991d5e056e694bb6177ad`.
- Previous Lite source: `lite-source-cfe84b24cd0a0255`, SHA-256 `cfe84b24cd0a0255c21aa211e9001dd3e77552403367e6fd7eb1a00b25d7e982`.

Private release receipts under the ignored `test-results/civo-13-nov` directory record the backups and integrity comparison. This release did not run Kaito's licensed research-data validation.
