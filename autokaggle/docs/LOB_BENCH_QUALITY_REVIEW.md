# LOB-Bench evaluator check — 12 November 2026

The test uses a separate copy of the accepted LOB-Bench contract. It does not change the researcher's original session or published evaluator. The model is DeepSeek V4 Pro through OpenCode 1.19.5. Each coding round retains the existing 30-minute and 150-request limits.

## Verified findings

- The first separate code review found a feature-list test that did not test behavior. It also found incomplete validation of submitted message CSVs and an implementation path that differed from the accepted scorer command.
- Failed coding rounds originally lost their working code. The service now saves bounded code drafts and review evidence. A new coding turn can continue that work. It excludes downloaded assets, credentials, and dependency caches.
- Replanning the unchanged contract changed requirement IDs and consumed time. Coding revisions now reuse the validated frozen plan for the same contract digest.
- One planning round searched the whole container and spent ten minutes in a file search. The prompts now name the local schema file and restrict searches to the evaluator workspace.
- Saved output inspection found missing OFI divergence values. These values need a separate scientific decision. They are not all evidence of insufficient synthetic data.

## Undefined OFI diagnostics

The accepted protocol uses a divergence horizon of 50 messages. The pinned scorer divides the generated sequence into windows of that length. Its four order-flow-imbalance features use a rolling window of 100 messages. They therefore cannot produce the corresponding Wasserstein and KS divergence values in a 50-message segment. The official plotting code excludes OFI curves.

This limit concerns the divergence diagnostics. It does not by itself invalidate the headline WS-21 score on the complete 250-message generated windows. The other 17 divergence features and the six price-response event types still require actual measurements and meaningful output tests.

Evidence at the accepted source commit:

- [OFI calculation and its default window](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/scorer/lob_bench/eval.py#L482).
- [Division into divergence windows](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/scorer/lob_bench/scoring.py#L573).
- [Exclusion of OFI curves from the official plot](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/scorer/lob_bench/run_plotting.py#L500).

The researcher must decide whether to retain the 50-message protocol and explicitly mark those four curves unavailable, or change the diagnostic settings. A different horizon changes the diagnostic comparison and needs acceptance. An agent-written note or a test asserting null values is not approval of that rule.

The accepted metric definition explicitly rejects missing or non-finite required secondary measurements. It therefore conflicts with those undefined values. The final live coding turn reported this conflict and left the release in **Draft · a decision is needed**. It reused the 73-requirement plan and finished after 49 model requests in 339.2 seconds.

Do not assume that the scorer's default horizon of 100 resolves the conflict. Price differences remove one observation before the 100-observation rolling calculation, and conditional OFI features need further observations. Any replacement horizon must be tested with the pinned scorer before it is recommended as a resolution.

The build and review prompts now require evidence for a proposed remedy. A separate live DeepSeek review rejected the untested horizon-100 proposal. This was a focused prompt check; it was not another scorer execution or a successful evaluator release.

## Remaining evidence

The owner deferred the licensed research-data check. No result from this test qualifies the original problem for BOLD OS registration. A completed release still needs a controlled run on the declared research data and approval of that exact commit and report.

The review email transport test reached Gmail's accepted state using only the owner's account. It did not send an invitation to the researcher. The complete deployed email sign-in and return journey remains unclaimed.
