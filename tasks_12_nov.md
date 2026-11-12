# AutoKaggle tasks — 12 November 2026

## Approved outcome

Deploy the completed and tested changes to the Full and Internal Lite services on the existing AutoKaggle Civo cluster. Preserve existing projects and access settings. Keep interface and interview changes on `codex/agent-led-task-workflows`. Use `yhg01` for scratch evaluation repositories.

## Work and evidence

- [x] Review recent changes and PR #16; fix defects, test, then merge if sound.
  - Merged as 0c38f7be8a0b67baf430da541643d7264ef91c72 after release fixes in ba10a67.
  - Original PR: 1,466 Python tests passed, three skipped; 273 JavaScript tests passed.
  - Review branch: `codex/lite-review-deepseek`.
- [ ] Configure DeepSeek for live Full and Lite services. Keep the key in private configuration.
  - Live Full NetHack scope and source search passed with DeepSeek V4 Pro. The response token limit was increased after reasoning exhausted the old limit.
- [ ] Test Lite evaluation modules, private repository publication, clean-clone execution, fitness output, invalid submissions, and reproducibility records.
  - Fixed an unnecessary second execution of a failed seed and a token-publishing defect that updated HEAD. Thirty build/release checks passed, including Docker; four focused regressions passed.
  - Browser optimization journey created a private yhg01 repository. A clean clone scored a separate candidate correctly (fitness 4.0). ZIP and config contents were checked.
  - Civo supplies onboarding and publication. Researchers run their experiments locally.
- [ ] Replace the row of rigid chat controls with agent questions and context-specific actions. Preserve secondary tools.
- [ ] Support different problem settings while keeping provenance and evaluation requirements.
  - Work includes environments, optimization, forecasting, generation, and custom metrics.
- [ ] Support multiple chat attachments, including documents, tables, text, code, and images. Test empty, oversized, invalid, and partial-failure cases.
- [ ] Test actual researcher problems from the deployed admin records. Use copied test projects; preserve original sessions.
  - Selected NetHack, Fourier/PDE, limit-order-book trading, order-book generation, and sensor fusion.
  - Live DeepSeek replays passed for all five cases. Browser NetHack and LOB-Bench interviews are in progress. Licensed reference data remains a valid blocker for LOB-Bench.
- [ ] Find and review the existing large-repository import work. Store and inspect repositories on Civo. Pin revisions, enforce storage and download bounds, protect credentials, and support cleanup.
  - Existing implementation read twelve small files. Added streamed, pinned source snapshots and local search. LOB-Bench snapshot: 26 files, 8,720,642 bytes, commit 276baf3039bf7630b555891b9d04ad49a92b3356.
- [ ] Test repository import with LOBBench and its paper: https://arxiv.org/abs/2502.09172.
- [ ] Run all affected automated checks, browser journeys, download checks, and live model tests. Fix identified defects.
- [ ] Commit and push the work. Deploy tested changes to Civo and check the live services.
- [ ] Report completed changes, tested behavior, and any remaining external dependency or product limit.

## Current external limit

The browser declined the result-file upload. A request to enable uploads is pending. Do not substitute an API upload for that rejected browser action. Other tests continue.

## Resources

- Repository: https://github.com/yhg01/AutoKaggle
- PR #16: https://github.com/yhg01/AutoKaggle/pull/16
- Full: https://ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/
- Lite: https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite
- Civo cluster: `ecc962fa-2f4c-4a3f-96c4-179af273fb7a`, region `lon1`, namespace `autokaggle-web`.

## Evidence rules

A saved definition is not a measured evaluation. A generated module is not verified until it runs against checked examples. Model replays do not replace browser tests. Missing assets remain explicit blockers. Do not store secrets or private researcher transcripts in this file or Git.
