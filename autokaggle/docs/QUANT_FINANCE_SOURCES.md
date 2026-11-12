# Quant-finance source review

Checked on 9 November 2026. This is a source review. No external code was run. No market data, model weights, GPU allocation, or scientific result was produced.

## Located sources

| Source | Revision inspected | Role |
| --- | --- | --- |
| [BOLD sigma-0](https://github.com/bold-lab-ai/sigma-0) | `3e94398b7f7c8a84412f3a33d604aae937933ce4` | Training, inference, matching engine, replay environments, checkpoints, and benchmark adapters. |
| [nanoSigma](https://github.com/bold-lab-ai/nano-sigma) | `4b26ea39292a47421dba3d742207c9d080552b67` | [Public results website](https://bold-lab-ai.github.io/nano-sigma/). The inspected branch contains site files and cached results. |
| [LOB-Impact](https://github.com/george-nigmatulin/lob_impact) | `0aaf6bfeb17fe8aad6937c7cb7ca4881971f4431` | Analysis of generated intervention rollouts. [Paper](https://arxiv.org/abs/2610.27100), [project page](https://george-nigmatulin.github.io/lob_impact/). |
| [LOB-Bench upstream](https://github.com/peernagy/lob_bench) | `276baf3039bf7630b555891b9d04ad49a92b3356` | Distribution and impact-response benchmark. [ICML 2025 paper](https://arxiv.org/abs/2502.09172). |
| [FLAIROx lob_pipeline](https://github.com/FLAIROx/lob_pipeline) | `6d5eb2a9f2842fdce26dceaf77fe73b314aecab3` | Existing checkpoint-to-inference-to-scoring launchers. |
| [Sat-A LOB-Bench](https://github.com/Sat-A/lob_bench) | `2aa7d5d844b5a051c9474cf598e10d7f46f39506` | One source of sigma-0's merged scorer. |

No separate LOB-Bench repository appeared in the accessible BOLD organization list. BOLD's implementation is in sigma-0 under `src/lobpipeline/scorer/lob_bench`. The merge record pins its sources and the resulting tree hash. Use that complete scorer revision when reproducing BOLD results; upstream LOB-Bench is not automatically equivalent. [Merge record](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/scorer/merge.json)

sigma-0 supplies runnable source that the nanoSigma website repository lacks. The inspected sources do not establish that a specific sigma-0 commit reproduces every nanoSigma result. The exact checkpoint, tokenizer, data, benchmark configuration, and environment still need confirmation. No nanoSigma paper link was found in its inspected site or repository.

## The tasks need distinct contracts

| Task | Participant artifact and evaluation input | Scoring contract |
| --- | --- | --- |
| Return forecast | Predictions, or frozen code/checkpoint that consumes approved market history. Private future returns remain in the scorer. | Pearson IC, rank IC, or direction accuracy at declared horizons. Specify message-count or wall-clock horizons, anchor time, zero-return rule, coverage, and aggregation. |
| Generative market model | Frozen model, tokenizer, and generation adapter; conditioned on approved historical windows. | Compare generated and real message/book sequences. Declare feature set, conditioning bins, normalization, distance, horizon, and missing-feature policy. |
| Market-impact simulator | Generator plus simulator adapter with matched intervention and control runs. | Separate balance, attribution, exponent, amplitude, and relaxation diagnostics. A ranking rule needs an explicit scientific decision. |
| Historical trading policy | Forecast-to-position policy or agent; causal market inputs. | Net PnL after specified spread, fees, slippage, latency, sizing, and risk rules. This measures a historical simulation, not future market performance. |
| Message likelihood | Checkpoint, tokenizer, and evaluation code. | Nats per message, with a fixed field inclusion and token-width rule. Per-token losses from different encodings are not directly equivalent. |

These are implementation requirements inferred from the inspected sources. The common platform should preserve task identity instead of forcing each task into a supported tabular metric.

## Exact evaluator details that matter

**LOB-Bench.** sigma-0 supports unconditional, conditional, context, time-lagged, and divergence modes. WS-21 is valid only for the complete, pinned set of 21 unconditional features. Other modes return their own distances. A missing feature must fail that aggregate. Divergence returns a curve with explicit nulls for windows that cannot be scored. The adapter defaults to 48 workers; AutoKaggle must override this through an approved resource limit. [Scoring adapter](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/lob_bench/scoring.py)

The benchmark documentation identifies a structural-zero problem in contextual L1. It also explains that bootstrap intervals can change with score order and sharding because the scorer uses mutable random state. Pin execution order and worker/shard policy when intervals matter. Do not use a known defective score as the primary metric without a reviewed correction. Some copied guides describe an older output schema; use tested source contracts. [Benchmark notes](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/docs/benchmarking.md), [bootstrap implementation](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/scorer/lob_bench/metrics.py)

The inspected Wasserstein implementation standardizes the combined real and generated feature values with their sample standard deviation. It then computes the one-dimensional Wasserstein distance. WS-21 averages those distances over the exact feature list. A new scalar Wasserstein scorer, or nanoSigma's conditional score, must not be called WS-21. [Distance implementation](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/scorer/lob_bench/metrics.py)

**Return bench.** Event-anchored evaluation uses the last observed price at or before the target time. Both generated and real sequences must cover that horizon. A short sequence cannot silently stand for the requested horizon. Direction accuracy excludes realized returns within `1e-8` of zero. Pearson/Spearman results can be undefined; report a null with a reason, not zero. The code distinguishes resting-order side from aggressor side. [Metric implementation](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/lobpipeline/return_bench/event_anchored.py)

Pearson includes zero returns. Spearman uses average ranks for ties. Direction accuracy retains a zero prediction when the realized return is nonzero; that prediction is incorrect. Test constant arrays, tied ranks, all-zero reference returns, missing IDs, duplicate IDs, shuffled prediction order, and incomplete horizons before accepting a native forecast scorer.

**Likelihood.** sigma-0 calculates nats per message from field loss times token width. It distinguishes absolute-time fields and reference fields, and records missing expected fields. AutoKaggle must freeze that choice before comparison. [Message likelihood implementation](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/src/base_model/evaluation/message_perplexity.py)

**LOB-Impact.** The analysis repository consumes generated rollouts. It does not supply model training, market data, or the simulator. Visible and blind intervention arms must share the declared schedule and comparison conditions. The output is a diagnostic suite. Its synthetic example has a constructed square-root response; passing it tests the tools only. [Protocol and input layout](https://github.com/george-nigmatulin/lob_impact/blob/0aaf6bfeb17fe8aad6937c7cb7ca4881971f4431/README.md)

## Reproduction and resource requirements

For one sigma-0 model-zoo experiment, training seeds are `5, 42, 137`; generation seed is `2026`. It freezes 3,136 January 2026 windows, 500 conditioning messages, and 500 generated messages. December 2025 data select checkpoints; January data score them. These are that experiment's settings, not universal defaults or established nanoSigma settings. Training uses four nodes with four GPUs each. The protocol separates within-run bootstrap uncertainty from variation across training seeds. [Frozen model-zoo protocol](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/docs/experiments/model_zoo/protocol.md)

Data are paired message/book arrays, with time and book alignment rules. Large corpora use monthly SquashFS shards and file indexes. Many data and model entries are symlinks to Isambard storage; a Git clone does not include those payloads. Record portable artifact references, hashes, access checks, and permitted use. [Data formats](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/docs/data.md)

Pin the checkpoint step and full payload digest, tokenizer, model configuration, and restore options. Metadata hashes alone do not bind all model weights. sigma-0 documents checkpoint-era normalization and Orbax compatibility; a wrong restore can produce plausible but wrong output. [Checkpoint guide](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/docs/checkpoints.md), [environment guide](https://github.com/bold-lab-ai/sigma-0/blob/3e94398b7f7c8a84412f3a33d604aae937933ce4/docs/environments.md)

The Full verifier must keep participant execution separate from private reference streams and scorer credentials. External score pickles are untrusted and must never be loaded by the web service. Only a pinned trusted scorer may produce its own intermediate files inside a controlled job. GPU count, hardware, time, memory, storage, network access, and cancellation must be enforced. Source import does not approve a compute allocation.

## Practical implementation order

1. Add a quant task contract to the interview and generated package. Keep observed facts, adopted protocol choices, and missing dependencies separate.
2. Require chronological boundaries, window identity, overlap policy, horizon units, and data-availability times. Keep private windows and answers out of participant files.
3. Support exact scalar forecast metrics first. Use server-owned return labels and a frozen horizon contract. Reject incomplete IDs, nonfinite predictions, unsupported aggregation, and undefined primary scores.
4. Add a versioned adapter registry for generative and intervention benchmarks. Each adapter declares schemas, metrics, dependencies, resource bounds, and a trusted command. Never execute an arbitrary imported repository as an evaluator.
5. Package the website, README, participant instructions, config, and verifier plan consistently. Mark execution pending until data access, adapter checks, controlled runner, and measured submission checks pass.
6. Use small synthetic paired streams to test parsing, pairing, causality, metric arithmetic, and failure handling. Label this as an engineering test. A real scientific run still needs authorized data, weights, exact protocol, and approved compute.

This order supports useful quant onboarding now while preserving the distinction between a defined challenge, a generated package, and a measured verification result.
