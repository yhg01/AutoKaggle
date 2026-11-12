# Verifier software quality and iteration — 12 November 2026

## Approved scope

Work in `codex/contract-coverage`, in a separate worktree. Open a PR. Preserve existing researcher sessions and published evaluator tags. Use copied sessions and `yhg01` scratch repositories for end-to-end tests. Do not add cloud nodes or increase the existing compute allowances.

Treat each generated verifier as a complete software project. The accepted scientific contract controls implementation. Changes to scientific meaning need researcher acceptance. Changes to implementation must retain the accepted contract and prior release history.

## Delivery checklist

- [x] Freeze a source-linked, testable requirement specification before implementation. Cover all applicable contract fields and each required metric, output, validation, reference identity, resource rule, and failure rule.
- [x] Require executed tests mapped to requirements. Test representative cases, invalid inputs, edge cases, provenance, saved outputs, and failure handling. Copied-reference examples are explicit oracle sanity checks, not evidence of research quality.
- [x] Add a separate coding review against the complete contract and executed tests. Bound all agent work. Preserve review findings, repair attempts, usage, and limitations.
- [x] Distinguish build completion, contract/test coverage, synthetic validation, and research-data validation. Legacy releases remain explicitly unassessed. Missing licensed data must never receive a research-validated status.
- [x] Provide a standard result bundle with required primary/secondary metrics, durable output files, reference-data identity, checksums, seeds, resource records, and validation evidence.
- [x] Support locally supplied licensed assets, declared downloadable assets, directory/sharded inputs, streaming digests, and bounded safe archive handling. Keep test-code limits separate from research-data size. Check available resources before runs.
- [x] Verify existing Lite build email behavior. Add a recorded, retryable invitation to inspect the build. Test email using the owner's test account; do not send test mail to Kaito.
- [x] Support conversational coding iteration from the existing release, with prior context and measured failures. Route scientific changes back to contract review. Re-test and release a new version; preserve the old version.
- [ ] Test the UI return journey: build email/link, reopening the session, code feedback, bounded coding work, new results, and downloads.
- [ ] Run the full workflow on a copy of Kaito's LOB-Bench contract. Check all metric/output requirements, invalid window and feature cases, reference provenance, and an iteration. Clearly report licensed-data checks that cannot run.
- [ ] Run general regression cases across prediction, environments, optimization, forecasting, and generation. Include live DeepSeek model calls, browser tests, clean-clone/ZIP execution, and failure tests.
- [x] Review the OpenCode versus DeepSeek Harness choice using official sources. Do not attribute a contract/test design defect to a harness without evidence.
- [ ] Update documentation, commit, push, and open a PR with verified evidence and remaining limits.

- [x] Register eligible releases in BOLD OS Problem Bank and Benchmarks only after a controlled research-data check and human approval. Keep stable project IDs and exact release commits.

## Initial findings

The old build pipeline validates a scalar fitness on exactly three fixtures. The same coding job chooses those fixtures and their expected-score calculation. It does not systematically establish complete contract coverage. The generated LOB-Bench adapter drops required secondary outputs and reference identity. Its price-response step ignores failures. Generic input checks do not enforce all declared windows or feature names.

The current build prompt asks for exact implementation, but instructions alone are not enforcement. Release status and acceptance tests must state what was actually established.

OpenCode is pinned to 1.19.5 in the current runtime. The official DeepSeek Harness repository describes a developer preview with breaking changes. Keep OpenCode for this implementation unless a reproducible harness fault changes that decision. Both harnesses need the same independent contract and software checks.

## Evidence

Private researcher records, credentials, generated scratch data, and raw model logs belong only in ignored `autokaggle/test-results/contract-coverage/` or private local configuration. Never commit them. Record small synthetic regression fixtures in tests where appropriate.

## Scope update

The owner deferred Kaito's licensed research-data validation. Do not claim that this run passed or register the problem as validated. The BOLD OS Research menu contains Soon placeholders for Problems bank and Benchmarks. The pages, write API, search, rules, and history are implemented and pushed in BOLD OS branch `codex/problem-bank-benchmarks`. That branch is not deployed and has no PR to main. AutoKaggle keeps eligible deliveries pending until an approved acting token and the deployed endpoint are configured.

## Verification in progress

- AutoKaggle JavaScript: 281 tests passed.
- Python full run: 1,570 passed, one skipped. After later revision and registration fixes, the build group passed 47 tests (one skipped), and the research/registration group passed 23 tests.
- The copied LOB-Bench interview was opened through the browser. Its ZIP downloaded and passed the archive check. Coding feedback was submitted through the chat. The live DeepSeek/OpenCode job produced 73 contract requirements. Its separate review found missing generated-CSV checks and a feature-list test with no behavioral assertion. Repair and re-review are running.
- Gmail accepted a transport test sent only to the owner's account. Invitation content, saved send status, and duplicate protection passed integration tests. The local preview does not use production email sign-in; the complete deployed invitation journey is not claimed.
- BOLD OS: 195 tests and the site build passed. The demo Firebase test passed registration, simultaneous retries, permissions, search, and database-rule checks. Browser checks covered both pages, notes, archive/restore, sign-out, another member's read-only controls, and light/dark/mobile layouts.
- The AutoKaggle registration sender also passed against the local BOLD OS HTTP receiver, with a clearly labelled synthetic integration record. Both records and the exact-commit receipt were saved. A repeated delivery reused the receipt. This is an integration test, not a validation claim about Kaito's data.
- Work is committed per solved sub-problem. The AutoKaggle PR remains to be opened after final checks.
