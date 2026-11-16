# Civo release — 16 November 2026

AutoKaggle PRs [#22](https://github.com/yhg01/AutoKaggle/pull/22) and [#24](https://github.com/yhg01/AutoKaggle/pull/24) are merged. Full and Lite use application commit `0b50a8e4f4fa1a5521189b842e82d84037cb5b93`.

Source SHA-256: `d90a5388cd29aee93b39482290661796ffed088c0f8c6a1f75396c8218a19c24`.

- Full: `source-d90a5388cd29aee9`, deployment `web`.
- Lite: `lite-source-d90a5388cd29aee9`, deployment `lite`.
- Namespace: `autokaggle-web` in the existing London Civo cluster.
- [Full](https://ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/) and [Lite](https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite).

## Changes and access

The release includes six bounded BOLD OS read tools, the local BOLD OS skill, and automatic registration checks. The server waits for research-data validation and human approval of the exact release before sending a Problem Bank record. The approval view explains the destination and shows a Problem Bank link after a confirmed receipt.

Deployment review moved the trusted interview access marker into the provider wrapper. The package-generator bytes now match the previous release. Existing package identities and states were preserved.

The source is deployed; the OS connection is not enabled. Lite retains the temporary `verified_email` policy. Shared OS reads and writes require approved member access. The registry URL remains unconfigured. BOLD OS PR [#31](https://github.com/bold-lab-ai/bold-os/pull/31) stays open for Eduardo. No BOLD OS production change was made.

## Verification

- Both services had zero active project jobs before restart.
- The 35 Full and 12 Lite project bodies matched their original hashes after deployment. Package identities and states matched. The eight existing stale Lite packages stayed stale; the deployment did not change their state.
- Both SQLite backups and live databases passed integrity checks. Access settings and deployment settings outside the source update matched their original values.
- Both services became ready and served the new UI code over HTTPS. Anonymous admin requests returned HTTP 403.
- The Full browser reopened a saved interview with its conversation and checklist. The Lite browser displayed its sign-in page. A new signed-in Lite browser session and email delivery were not tested in this release.
- 137 backend tests passed; one optional Docker runtime test was skipped. All 57 Lite UI tests passed.
- A live `deepseek-v4-pro` test with the revised member connection used five successful BOLD OS read tools and asked for project confirmation. It took 18.1 seconds.
- A separate live `deepseek-v4-pro` call from the deployed Lite pod returned a valid NetHack follow-up and kept OS tools disabled under public email access. It took 130.6 seconds. Response latency remains a limitation.

No OpenRouter coverage, new evaluator build, or research-data validation is claimed. Private operational receipts are in the release operator's ignored `autokaggle/test-results/civo-16-nov` directory.

## Source rollback

Restore the previous source ConfigMap and its matching source-hash annotation. Keep current data and Secrets. Do not restore an old database for a source rollback.

- Previous Full: `source-e985108f5972a6b5`.
- Previous Lite: `lite-source-e985108f5972a6b5`.
- Previous SHA-256: `e985108f5972a6b50e15393a2b26738aa078fcb0d7d12449783a9fc76b3bd820`.

The private backups are `/data/projects/backup-20261116-132304.sqlite3` on Full and `/data/projects/backup-20261116-132158.sqlite3` on Lite.
