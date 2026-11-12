# Lite validation — 5 November 2026

This record covers the internal Lite implementation on branch `internal-autokaggle-lite`. The live Full service and Eduardo's saved session were not changed. The tests used separate local data stores.

## NetHack workflow

The browser test imported the [BALROG paper](https://arxiv.org/abs/2411.13543) and the [NLE repository](https://github.com/NetHack-LE/nle). The repository import recorded commit `2319f2989f0035685017e9ea13c83b2546fe477c`. The researcher supplied a short objective and two follow-ups about local limits and dependencies. The model proposed the remaining fields for explicit review. All six decision groups were then resolved.

Live model: OpenRouter `openai/gpt-6.1-sol`, medium reasoning. The first response contained an invalid enum value. The parser now preserves valid proposed fields and shows invalid fields for correction. Retry preserved the message and source records. The retry and both follow-ups succeeded. A separate direct diagnostic call helped locate the invalid field.

The browser created the package, opened its website, downloaded the ZIP, and uploaded the measured result report. The browser download SHA-256 matched the server ZIP. Session resume preserved the contract, messages, and result.

A later live revision used the saved attempt summary. It changed only the requested manifest field name and kept the scientific settings. The reply correctly distinguished structural checks from independent reproduction and identified the earlier result as historical. Revision context now also includes separate counts for natural completion, truncation, timeout, and failure.

Execution used the released `nle==1.3.0` wheel, Python 3.11, `gymnasium==1.2.0`, `numpy==2.2.6`, and `torch==2.6.0+cpu`. The imported repository commit was source evidence, not the executed NLE build. The package used `NetHack-v0`, its standard 86 actions, both NLE random seeds, and `info['is_ascended']`. The checkpoint was a real PyTorch tensor that always selected WAIT. It had no training.

The test container had two CPU cores, 2 GiB RAM, no network, no GPU, a read-only root filesystem, and a writable test directory. Each episode had a 100-step and 30-second limit. The whole run had a 900-second limit. This local container test does not establish a security boundary for public submissions.

| Measured item | Result |
| --- | --- |
| Assigned seeds | 100; all recorded |
| Natural terminations | 10 |
| Episodes stopped at the step limit | 90 |
| Process failures or timeouts | 0 |
| Environment steps | 9,527 |
| Sum of per-episode wall time | 219.15 seconds |
| Ascensions | 0 |
| Aggregate success rate | 0.0 |
| Uploaded evidence status | `evidence_checked`; independent reproduction false |

The run used contract `908a75c8bb4f9c9617f17d80`. The local loader commit was `0410a5a705c8f47bc9fe434c007ff8c1ab8ed937`. The checkpoint SHA-256 was `6d088243f6eec694af9112b896c765f24a90568edfef4ec698d67bda0e1bb9d0`.

The final package was run again after the manifest correction and package updates. This run used contract `c6b498472d5ee002f072324a`, with its new fixed seed list. The checkpoint, environment, and resource limits were unchanged. All 100 seeds produced records: four episodes ended naturally and 96 reached the step limit. There were no process failures or timeouts. The run made 9,851 environment steps and used 195.61 seconds of summed episode time. There were no ascensions, so its success rate was 0.0. The report was uploaded through the browser. The website then showed one report for the current version, and the previous report remained saved under its earlier version.

The runner's summary field `failed` counts all episodes that did not complete, including step-limit truncation. The per-seed records retain each status. These 96 truncated episodes were not process failures.

These are measured workflow results from an untrained policy. They do not reproduce Eduardo's proposed training method, an ascension baseline, or an unrestricted long-horizon evaluation. His actual checkpoint and its training provenance are still needed for that experiment.

## Generic batch workflow

A second isolated test used real OpenRouter responses to define a small supervised batch task with local synthetic data. It built and downloaded a package, ran a frozen prediction CSV through a custom adapter in separate processes, and submitted the measured report.

- Both assigned runs measured accuracy 0.75.
- A duplicate request reused the saved result.
- Missing seeds and out-of-range accuracy were rejected.
- A live model correction changed the run count from two to three. The previous ZIP became stale, and rebuilding produced a new version.
- The earlier report remained attached to its original two-run contract. It was not scored under the later three-run contract.

This test establishes that the adapter and evidence flow also work outside an RL environment. New dataset formats and environments still need their own tested adapter.

## Coverage and remaining limits

Automated checks cover contract types, proposal acceptance, source evidence, PDF extraction, import bounds, retries, restart recovery, owner access, lab membership, deletion, Full/Lite isolation, versioning, artifact hashes, complete seed coverage, score bounds, process deadlines, stale packages, and safe website rendering. Browser checks cover the actual interview, proposal review, package download, website, result file upload, and session resume.

The full Python suite passed 1,257 tests. After the final handoff and result-context fixes, 84 affected Python checks passed. The 29 Lite client checks passed. A denied handoff did not consume its code or grant access; an approved lab member could resume in Lite and could be removed by the owner.

The service checks submitted evidence structure and version bindings. It does not fetch a checkpoint or independently rerun it. Fixed Lite seeds are visible. A declared training method and budget remain researcher reports. Hosted GPU execution, independent reproduction, private source connectors, and Full compute enforcement need separate implementation and validation.

Local test evidence is excluded from Git under `autokaggle/test-results/lite-live/` and `autokaggle/test-results/lite-batch-live/`. Those directories include the actual contracts, source snapshots, downloaded packages, checkpoint fixture, dependency lock, result reports, and browser proof. No keys or account tokens belong in this document.
