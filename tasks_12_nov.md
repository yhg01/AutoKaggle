# AutoKaggle tasks — 12 November 2026

## Approved outcome

Deploy the completed and tested changes to the Full and Internal Lite services on the existing AutoKaggle Civo cluster. Preserve existing projects and access settings. Keep interface and interview changes on `codex/agent-led-task-workflows`. Use `yhg01` for scratch evaluation repositories.

## Work and evidence

- [x] Review recent changes and PR #16; fix defects, test, then merge if sound.
  - Merged as 0c38f7be8a0b67baf430da541643d7264ef91c72 after release fixes in ba10a67.
  - Original PR: 1,466 Python tests passed, three skipped; 273 JavaScript tests passed.
  - Review branch: `codex/lite-review-deepseek`.
- [x] Configure DeepSeek for live Full and Lite services. Keep the key in private configuration.
  - Deployed to both services.
  - Live Full NetHack scope and source search passed with DeepSeek V4 Pro. The response token limit was increased after reasoning exhausted the old limit.
- [x] Test Lite evaluation modules, private repository publication, clean-clone execution, fitness output, invalid submissions, and reproducibility records.
  - Fixed an unnecessary second execution of a failed seed and a token-publishing defect that updated HEAD. Thirty build/release checks passed, including Docker; four focused regressions passed.
  - Browser optimization journey created a private yhg01 repository. A clean clone scored a separate candidate correctly (fitness 4.0). ZIP and config contents were checked.
  - Civo supplies onboarding and publication. Researchers run their experiments locally.
  - Live Civo build and private yhg01 publication passed ten acceptance checks. A separate fresh clone returned fitness 16 on three seeds and rejected invalid input. The production BOLD credential and owner were restored.
- [x] Replace the row of rigid chat controls with agent questions and context-specific actions. Preserve secondary tools.
- [x] Support different problem settings while keeping provenance and evaluation requirements.
  - Work includes environments, optimization, forecasting, generation, and custom metrics.
- [x] Support multiple chat attachments, including documents, tables, text, code, and images. Test empty, oversized, invalid, and partial-failure cases.
- [x] Test actual researcher problems from the deployed admin records. Use copied test projects; preserve original sessions.
  - Selected NetHack, Fourier/PDE, limit-order-book trading, order-book generation, and sensor fusion.
  - Live DeepSeek replays passed for all five cases. Browser NetHack, Fourier/PDE, and LOB-Bench interviews passed. Licensed reference data remains a valid blocker for LOB-Bench.
- [x] Find and review the existing large-repository import work. Store and inspect repositories on Civo. Pin revisions, enforce storage and download bounds, protect credentials, and support cleanup.
  - Existing implementation read twelve small files. Added streamed, pinned source snapshots and local search. LOB-Bench snapshot: 26 files, 8,720,642 bytes, commit 276baf3039bf7630b555891b9d04ad49a92b3356.
- [x] Test repository import with LOBBench and its paper: https://arxiv.org/abs/2502.09172.
- [x] Run available automated, browser, download, and live model checks. Fix identified defects.
  - Final suite: 1,509 Python tests passed, one opt-in Docker check skipped; 274 JavaScript tests passed. Docker was checked separately.
- [ ] Complete the two browser checks blocked by saved permissions: deployed Lite origin and result-file upload.
- [x] Commit and push the work. Deploy tested changes to Civo and check the live services.
  - Both services run source digest `c909b1150ecd43a9511408c2f60b2003400a8bb706d991d5e056e694bb6177ad`.
  - All 34 original Full projects and six original Lite projects are unchanged. Health and anonymous-access checks passed.
- [x] Record completed changes, tested behavior, and remaining external dependencies and product limits.

## Validation record

See `autokaggle/docs/VALIDATION_2026-11-12.md` for test evidence, release commits, and limits. Feature PR: https://github.com/yhg01/AutoKaggle/pull/17.

## Current external limit

The browser declined the deployed Lite origin and the result-file upload. A request to enable uploads is pending. Do not substitute an API upload for that rejected browser action. Other tests continue.

## Resources

- Repository: https://github.com/yhg01/AutoKaggle
- PR #16: https://github.com/yhg01/AutoKaggle/pull/16
- Full: https://ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/
- Lite: https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite
- Civo cluster: `ecc962fa-2f4c-4a3f-96c4-179af273fb7a`, region `lon1`, namespace `autokaggle-web`.

## Evidence rules

A saved definition is not a measured evaluation. A generated module is not verified until it runs against checked examples. Model replays do not replace browser tests. Missing assets remain explicit blockers. Do not store secrets or private researcher transcripts in this file or Git.

## Follow-up: link-based imports

The owner requested GitHub and Google Drive links instead of a browser file upload.

- GitHub source import already passed the live Civo LOB-Bench test. It stores a pinned source snapshot and supports local reads and search.
- Google Drive dataset links are currently recorded as references. AutoKaggle does not download those files into its dataset or attachment store. This differs from the older problem-intake service.
- Lite result reporting currently requires the runner JSON report. A GitHub or Drive artifact URL in its manifest is a provenance reference; it does not import the report or independently verify the artifact. A result-report URL import is not implemented.
- After the owner reported enabling browser access, a new attempt to open the deployed Lite origin was still denied by the browser permission gate. No website request or login occurred. The cause cannot be assigned to this chat from the available evidence. No alternate route was used to bypass the denial.

## Temporary email access and BOLD OS handoff

The owner approved temporary admission for any verified email while Slack/BOLD OS sign-in is prepared for 13 November. The collaborator plan is `autokaggle/docs/LITE_BOLD_OS_AUTH_PLAN.md`. The implementation uses `AUTOKAGGLE_LITE_ACCESS_POLICY=verified_email`; private mode, email-code verification, project ownership, and administrator controls remain enabled. The member-list mode remains available.

Deployed temporary email access on 12 November at 11:22 UTC from commit `5cf7668`. Lite source digest: `b7fd58a1281cf41871fdbced740c19888f8eb7946867acb00bb3729adee498c9`. Full retains its previous source. The 134 focused tests passed. A live DeepSeek V4 Pro interview passed through a verified non-member account. Server checks confirmed non-member admission, anonymous denial, administrator denial, and private project isolation. All eight Lite project bodies were unchanged. Test identities were removed. Email delivery and browser sign-in were not retested.

## Approved BOLD GitHub connection — automatic publication

- [x] Connect successful evaluator checks to automatic private repository publication.
- [x] Keep one repository per problem and a pinned tag per tested version.
- [x] Show repository, ZIP download, publication progress, and retry after failure.
- [x] Keep the tested release after failed or interrupted publication; prevent concurrent edits during a push.
- [x] Support scoring from GitHub ZIP downloads with a recorded revision and file integrity checks.
- [x] Verify live publication under yhg01 and run the downloaded GitHub ZIP.
- [x] Complete BOLD publication after the token permission update. The existing tested release published successfully. Its GitHub ZIP returned fitness 16.0 over three seeds and rejected invalid input.
- [x] Deploy automatic publication to Civo Lite and verify all ten existing sessions were preserved.

See `autokaggle/docs/AUTO_PUBLICATION_2026-11-12.md` for the live browser test, deployment, and resolved GitHub permission blocker.

## Lite administrator log repair

- [x] Correct Lite project status and interview turn counts in the admin list.
- [x] Show saved Lite messages, definitions, revisions, source records, packages, results, and evaluator builds.
- [x] Capture new model requests and responses with private, bounded diagnostics.
- [x] Add administrator-only build logs and update Civo logs during a running build.
- [x] Check the UI with the affected saved session, a completed build, and a live DeepSeek interview.
- [x] Deploy after the existing Civo evaluator job finished. Live admin routes, new request traces, access denial, and preservation of all 11 project bodies passed. Source commit `3b31781`; digest `cfe84b24cd0a0255c21aa211e9001dd3e77552403367e6fd7eb1a00b25d7e982`.

See `autokaggle/docs/LITE_ADMIN_LOGS_2026-11-12.md` for cause, checks, and limits. Earlier Lite provider responses were not saved and cannot be recovered.

## PR review and monitoring follow-up

- [x] Review and merge PR #18 into the feature branch. GitHub file/archive links stay in chat; repository root links remain imports. A local browser test with DeepSeek V4 Pro confirmed the file-link path.
- [x] Final combined checks: 1,536 Python tests and 278 JavaScript tests passed; one opt-in Docker check was skipped. Lite rollout and live DeepSeek validation passed. PR #17 is ready for the authorized merge.
- [x] Schedule private checks every 15 minutes through 08:00 London time on 13 November. Record only new failures or changes. The desktop app and computer must remain running.
- [ ] Review the generated evaluator acceptance gap: primary-score fixture tests do not establish that all secondary outputs and reference-data provenance required by an accepted definition are implemented. A live generated release omitted these fields. Keep the private incident evidence outside Git. This needs a general acceptance change and a new evaluator release; do not alter the accepted scientific definition or replace a published tag.
