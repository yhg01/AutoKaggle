# Validation — 12 November 2026

## Changes

- DeepSeek V4 Pro supplies the Full and Internal Lite model calls. The API key stays in private configuration. Full responses have enough output allowance for reasoning and the structured answer. Lite can repair one malformed response before reporting a failure.
- Lite supports batch, environment, optimization, forecasting, generation, and custom scoring definitions. Conditional requirements cover constraints, temporal rules, generation protocols, and exact custom metrics. No field becomes an accepted fact without organizer review.
- Secondary tools are in the header. The chat offers the relevant package, evaluator, or result action. Multiple document, table, code, text, and image attachments are supported. File failures remain visible and retryable.
- Public GitHub repositories are stored as pinned source snapshots. The agent reads and searches them on the server. Imports enforce path, size, count, time, free-space, and session limits. They do not execute source code. Git history, submodules, and LFS downloads are excluded.
- Internal evaluator builds use bounded container jobs on the existing Civo node. The trusted application keeps the provider and publishing credentials. Researchers run experiments locally. Full retains its separate execution controls.

## Defects found and fixed

1. DeepSeek could use the previous response allowance entirely for reasoning and return no usable answer. The Full response allowance now includes room for both.
2. A failed evaluator seed ran a second time to obtain diagnostics. This used extra compute and could exceed the declared time budget. The first execution now records the diagnostics.
3. Token publication could try to update Git's HEAD alias when releasing a second version. Only the requested branch and tags are now updated.
4. The hosted isolated PDF reader could not find dependencies installed in `/runtime`. The reader now gets the trusted library location explicitly, while retaining Python isolated mode.
5. Civo did not expand an attached Lite volume. The volume needed an offline expansion. It now mounts 9.2 GiB with about 8.8 GiB free. The importer correctly refused the insufficient free space before expansion.
6. An environment's arbitrary truthy status could count as success. Generic success evaluation now accepts only booleans or integer 0/1 values. Other status codes require an explicit scoring adapter.
7. The next action could stay hidden after contract acceptance. Controls now update it after the busy state ends.

## Evidence

- PR #16: original suite, 1,466 Python tests and 273 JavaScript tests passed. Review fixes passed 30 build/release checks, including Docker, plus four focused regressions. PR #16 was merged as `0c38f7be8a0b67baf430da541643d7264ef91c72`.
- Feature suite: 1,509 Python tests passed, one Docker opt-in check skipped; 274 JavaScript tests passed. Subsequent focused checks cover the PDF, RL, deployment, and storage-notice fixes. The Docker check ran separately in the review suite.
- Five copied researcher cases were tested with live DeepSeek responses: NetHack, Fourier/PDE, order-book trading, order-book generation, and sensor fusion. Original researcher sessions were read only.
- Local browser tests covered a complete optimization interview, review, package download, config download, evaluator build, and private repository publication. NetHack recovery and protocol correction, LOB-Bench missing-data handling, and the Full numerical-problem interview were also exercised.
- The Civo backend built a separate optimization evaluator with 10 live DeepSeek requests. All 10 release checks passed, including a fresh environment, an independent score calculation, valid/wrong examples, invalid-input rejection, and unchanged tracked files.
- The tested Civo release is private: `yhg01/lite-eval-civo-evaluator-acceptance-12-nov-5ed02466`, commit `9110ec9ce279fcf7d9d94ae5c14e4eee0f46d9be`. A fresh local clone scored a new candidate at 16.0 on three fixed seeds and rejected a boolean candidate. The result records the code commit, contract digest, artifact digest, dependency digest, resource declaration, and all seeds.
- The ordinary research ZIP and separately downloaded config agree. The ZIP includes README, AGENTS.md, the contract, seed list, runner, adapter interface, environment notes, and submission schemas. The tested evaluator release includes implemented scoring code, pinned configuration, lock files, fixtures, asset retrieval, and one-command fitness output.
- LOB-Bench source: https://github.com/peernagy/lob_bench at `276baf3039bf7630b555891b9d04ad49a92b3356`. The source snapshot contains 26 files and 8,720,642 bytes. The 24-page paper at https://arxiv.org/abs/2502.09172 produced 61,978 text characters with the corrected Civo reader.
- A server extraction test processed 128 MiB in 1.74 seconds, with 64,220 KiB peak RSS. Temporary files were removed. This tests extraction, not wide-area download speed.
- Civo build boundary checks passed: non-root, read-only root, no service credentials, no project-store mount, and blocked application, cluster-API, and metadata access. Public HTTPS remained available for dependencies.
- Before testing new projects, deployment preservation checks found no changes to the 34 original Full projects or six original Lite projects. Private database backups were taken before each rollout.

## Limits

The browser denied the deployed Lite origin and a result-file upload. Approval requests remain pending. API checks are identified as backend checks; they do not replace the blocked browser actions. The separate Full Civo origin is accessible. Its LOB-Bench import produced a sourced draft through the browser.

The NetHack checkpoint interface and licensed LOBSTER reference data are not available for a scientific reproduction. These remain explicit requirements. No research score is claimed for those tasks. A synthetic scoring test proves the module path, not a published benchmark result.

Test repositories were created only under `yhg01`. The production owner is `bold-lab-ai`; the lab credential was restored after the publication test. No test repository was created in BOLD. BOLD OS Problem Bank and Benchmarks write integration remains a separate requirement.

Internal containers are for approved lab members. They are not claimed to withstand all hostile code. Full's separate security checks remain mandatory.

The live Lite LOB-Bench import also completed after the storage and PDF fixes. DeepSeek selected a generation task and asked for reference stocks, date windows, sample counts, and data access. A Full source-application action now shows a visible wait message while the first interview question is prepared.

Full live browser application of the LOB-Bench brief completed and asked for reference stocks, dates, and data permission. The DeepSeek scope response took several minutes. This is a remaining performance limit, not a completed speed improvement. The browser now shows a wait message during this step.

The temporary operator test session was revoked after the Civo backend checks. Anonymous project lists were empty and direct project access was denied on both services.

## Final deployment

Both Civo services run source digest `c909b1150ecd43a9511408c2f60b2003400a8bb706d991d5e056e694bb6177ad` from feature commit `30bf39d`. The later commits update documentation only. Both health checks passed. The Full browser reopened the saved interview after rollout. All 34 original Full project bodies and six original Lite project bodies match their pre-rollout backups. Both services retain private mode. Lite retains the production BOLD repository owner and credential.

Both persisted LOB-Bench snapshots contain the expected 26 files at the pinned commit. Local repository search found the scoring implementation. Final free storage was about 8.1 GiB for Full and 8.7 GiB for Lite. Full retains its onboarding runtime annotation and extra mounts.
