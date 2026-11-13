# LOB-Bench evaluator check — 12 November 2026

The test uses a separate copy of the accepted LOB-Bench contract. It does not change the researcher's original session or published evaluator. The model is DeepSeek V4 Pro through OpenCode 1.19.5. Each coding round retains the existing 30-minute and 150-request limits.

## Verified findings

- The first separate code review found a feature-list test that did not test behavior. It also found incomplete validation of submitted message CSVs and an implementation path that differed from the accepted scorer command.
- Failed coding rounds originally lost their working code. The service now saves bounded code drafts and review evidence. A new coding turn can continue that work. It excludes downloaded assets, credentials, and dependency caches.
- Replanning the unchanged contract changed requirement IDs and consumed time. Coding revisions now reuse the validated frozen plan for the same contract digest.
- One planning round searched the whole container and spent ten minutes in a file search. The prompts now name the local schema file and restrict searches to the evaluator workspace.
- Saved output inspection found missing OFI divergence values. These values need a separate scientific decision. They are not all evidence of insufficient synthetic data.
- The coding agent shortened test output with a shell pipeline that could hide a failed test's exit status. Build and review instructions now require the actual test status. A focused live DeepSeek check produced a command that returned zero for a passing test and one for a failing test. The server's separate acceptance process still checks its own exit status.
- Additional inspection found that a missing or invalid generation-seed record could become null in an otherwise completed result. The contract requires that seed. Build and review prompts now require negative tests for missing, malformed, and conflicting provenance. A focused live review rejected this silent-null behavior. A separate evaluator seed does not replace the generation seed.
- The sixth coding round passed its separate review and synthetic score checks. Its clean-clone coverage check then found two tests that read `build.json`, a build-only file. The release stayed blocked. Build instructions now state that tests must use shipped files. Failure summaries now show the saved assertion errors before scorer progress text. Two regression cases cover a failed coverage report with either zero or nonzero process status.

## Undefined OFI diagnostics

The accepted protocol uses a divergence horizon of 50 messages. The pinned scorer divides the generated sequence into windows of that length. Its four order-flow-imbalance features use a rolling window of 100 messages. They therefore cannot produce the corresponding Wasserstein and KS divergence values in a 50-message segment. The official plotting code excludes OFI curves.

This limit concerns the divergence diagnostics. It does not by itself invalidate the headline WS-21 score on the complete 250-message generated windows. The other 17 divergence features and the six price-response event types still require actual measurements and meaningful output tests.

Evidence at the accepted source commit:

- [OFI calculation and its default window](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/scorer/lob_bench/eval.py#L482).
- [Division into divergence windows](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/scorer/lob_bench/scoring.py#L573).
- [Exclusion of OFI curves from the official plot](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/scorer/lob_bench/run_plotting.py#L500).

On 13 November, the project owner approved retaining the 50-message protocol and explicitly marking the four OFI divergence diagnostics unavailable. The exception covers `ofi`, `ofi_up`, `ofi_stay`, and `ofi_down` only. Preserve the reason in the saved diagnostic output and README. Do not replace unavailable values with fabricated scores. All 21 full-window headline features, the other 17 divergence features, and the six price-response event types remain required.

The decision was entered through the copied session's scientific interview, reviewed, and accepted through the browser. Only `metric_definition` and `evaluation_protocol` changed. The rebuilt contract version is `e017f02e1b87b2f3912ae912`. The original researcher session remains unchanged during this test.

Before that approval, the accepted metric definition explicitly rejected missing or non-finite required secondary measurements. The fourth live coding turn reported the conflict and left the release in **Draft · a decision is needed**. It reused the 73-requirement plan and finished after 49 model requests in 339.2 seconds. The approved exception resolves that scientific conflict; it does not establish that the revised evaluator passes its software checks.

Do not assume that the scorer's default horizon of 100 resolves the conflict. Price differences remove one observation before the 100-observation rolling calculation, and conditional OFI features need further observations. Any replacement horizon must be tested with the pinned scorer before it is recommended as a resolution.

The build and review prompts now require evidence for a proposed remedy. A separate live DeepSeek review rejected the untested horizon-100 proposal. This was a focused prompt check; it was not another scorer execution or a successful evaluator release.

## Release result

The seventh coding round passed the separate 63-requirement review and every clean-clone acceptance check. All 140 evaluator tests passed. The independent scorer reproduced the copied-reference oracle score of 0 and the distinct synthetic example score of 0.17048869967190391. Invalid submissions received no completed score. The run used DeepSeek V4 Pro through OpenCode, with 68 model requests and 993.3 seconds of coding and review time.

Publication was triggered through the browser. The private [scratch evaluator repository](https://github.com/yhg01/lite-eval-generative-lob-world-model-accuracy-lob-bench-ws-6c6675e6) contains version `v1`, commit `12321e2f31c041f4a1130291633373b0912b2224`. The downloaded GitHub ZIP contains all 43 files covered by the release lock, the YAML config, and the exact expanded revision marker. The original researcher repository was not modified.

The downloaded ZIP also ran in a fresh bounded container. Its distinct synthetic example returned fitness 0.17048869967190391 and generation seed 1337. Both diagnostic files and their hashes were saved. The output inspection confirmed the four explicit OFI exceptions, 17 finite five-window divergence curves, and six price-response event types. Removing the generation-seed record from that artifact produced exit status 2 and zero completed seeds. This run used the GitHub download, not the coding workspace.

The interface correctly reports **Software checks passed; research validation pending**. It also reports that BOLD OS registration is not yet eligible. The local preview has no review email configuration. Its email return journey remains untested; the earlier Gmail transport check does not establish that journey.

## Remaining evidence

The owner deferred the licensed research-data check. No result from this test qualifies the original problem for BOLD OS registration. Research validation still needs a controlled run on the declared research data and approval of that exact commit and report.

The review email transport test reached Gmail's accepted state using only the owner's account. It did not send an invitation to the researcher. The complete deployed email sign-in and return journey remains unclaimed.
