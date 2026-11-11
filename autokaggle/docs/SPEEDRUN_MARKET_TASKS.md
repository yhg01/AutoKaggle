# Market benchmark Speedrun test record

Date: 9 November 2026. These are source findings and a test plan. The requested browser interviews have not yet run. Browser access is blocked by the tool setting. Do not treat the existing API tests as evidence of these UI journeys.

## Located resources

| Problem | Paper | Code or repository | Website |
| --- | --- | --- | --- |
| LOB-Impact Benchmark | [arXiv 2610.27100](https://arxiv.org/abs/2610.27100) | [lob_impact](https://github.com/george-nigmatulin/lob_impact), commit `0aaf6bfeb17fe8aad6937c7cb7ca4881971f4431` | [LOB-Impact](https://george-nigmatulin.github.io/lob_impact/) |
| nanoSigma | No nanoSigma paper found in its public repository or project page. [LOB-Bench](https://arxiv.org/abs/2502.09172) is related evaluation work, not a nanoSigma paper. | [nano-sigma](https://github.com/bold-lab-ai/nano-sigma), `gh-pages`, commit `4b26ea39292a47421dba3d742207c9d080552b67` | [nanoSigma](https://bold-lab-ai.github.io/nano-sigma/) |

LOB-Impact supplies analysis tools for generated market rollouts. Its README excludes the neural model training, rollout generation, market data, and order-book simulator. LOBSTER data requires separate access. The benchmark compares free generation, intervention, a matched blind control, and relaxation. Its result is several diagnostics, with explicit cases where a law cannot be identified. [Official repository](https://github.com/george-nigmatulin/lob_impact/blob/0aaf6bfeb17fe8aad6937c7cb7ca4881971f4431/README.md)

nanoSigma's public repository contains the website and score records. The inspected tree and history contain no training implementation, evaluator, dependency file, model checkpoint, or source dataset. The site describes several objectives, including distributional comparison, returns, and PnL. A displayed score does not supply the code or data needed to reproduce it. [Public repository](https://github.com/bold-lab-ai/nano-sigma/tree/4b26ea39292a47421dba3d742207c9d080552b67)

## Confirmed small issue

The source-import fallback used to call every repository a “starting implementation.” That is false for a repository containing only a results website. The fallback now calls it a source reference and leaves implementation availability for review. This changes no readiness gate.

## Larger issues for owner review

These items are not implemented by this change. The UI runs must still establish how the application presents each blocker.

| Issue | Evidence and responsibility | Proposed general change |
| --- | --- | --- |
| Source availability | nanoSigma's supplied public repository has no experiment implementation. The organizer must provide that material or identify its actual location. | Distinguish a paper, results website, dataset, and executable implementation during source review. Keep source claims separate from tested availability. |
| Limited source inspection | The current repository reader selects bounded README, dependency, and standard starter files. Here it sees nanoSigma's short README, not its website score definitions. This is a platform coverage limit. | Add bounded source-type detection and useful document selection. Preserve commit pinning, public-address checks, text limits, and the no-execution rule. |
| Custom evaluators | Full's built-in scalar prediction and episode metrics do not encode these complete benchmarks. This is an unsupported workflow, not evidence of a scorer defect. | Define a versioned benchmark-adapter interface with exact inputs, artifacts, multiple metrics, failure states, and trusted scoring. Do not rename these metrics to RMSE or success rate to pass a gate. |
| Runtime and data | LOB-Impact requires a model, matched rollout generator, simulator, and licensed data. nanoSigma's public site omits the runnable experiment. These are missing experiment dependencies. | Require reachable, versioned dependencies and data permissions before a runnable verifier is marked ready. Retain a draft while material is missing. |
| Compute and isolation | Checkpoint execution and substantial GPU work require an enforced runner and approved resources. Source import does not provide either. | Connect the approved compute request to a controlled runner with exact resource bounds, network policy, artifact versions, and cancellation. Keep public Full protections active. |

Do not generate a plausible-looking completed verifier or claim independent verification from these links alone. Do not invent a private dataset, seeds, budget, or permission. The organizer can refine the scientific scope while the implementation gaps remain visible.

## Required UI run

Use short replies and occasional requests for clarification. Start with the source links. Review what the agent extracts. Answer one missing decision at a time. For nanoSigma, first choose one primary benchmark and request the actual implementation if absent. For LOB-Impact, preserve its intervention and matched-control design.

Attempt draft generation, website review, research ZIP/config download, verifier preparation, and one revision. Record which actions succeed and the exact blocker for each failed action. Inspect downloaded files. Keep measured runs separate from templates. Fix clear small defects; seek owner approval for the larger changes above after the run.

Detailed source notes are retained locally under the ignored `autokaggle/test-results/three-paths-2026-11-09/` directory. No imported training code has been executed.
