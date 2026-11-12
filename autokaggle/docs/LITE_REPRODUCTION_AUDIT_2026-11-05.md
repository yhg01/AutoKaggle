# Submitted-result reproduction audit — 5 November 2026

The seven saved submissions can be replayed from the files retained on this laptop. All 50 seeded records matched their saved outcomes. The portal alone does not yet retain everything another lab member needs to reproduce them. It also does not enforce complete reproduction material for future submissions.

The audit read the actual live result records, including the two earlier versions. Every saved manifest/result fingerprint matched. All seven code and artifact references use `local:`. These references identify files on the submitting machine; they do not let another person retrieve the files.

Replays used fresh directories, freshly extracted downloaded ZIPs, and exact saved code revisions. Batch and MiniGrid/Pendulum runs used retained Python environments. NetHack used a new container from the retained image. None used a fresh environment build or an independent verifier. The audit changed no live result, evidence status or contract.

| Saved attempt | Seeds | Saved and replayed score | Per-seed comparison |
| --- | ---: | ---: | --- |
| Fashion-MNIST | 3 | Accuracy 0.1 | Exact match |
| Concrete, current | 5 | RMSE 17.331416868007572 MPa | Exact match |
| Concrete, earlier version | 5 | RMSE 17.568873853993736 MPa | Exact match |
| MiniGrid | 12 | Success rate 0.5 | Exact match |
| Pendulum, current | 10 | Mean return −875.3491158579911 | Exact match |
| Pendulum, earlier version | 10 | Mean return −1218.1683512745954 | Exact match |
| NetHack | 5 | Success rate 0.0 | Exact match; five 100-step truncations |

Compared fields were seed, status, score, steps and end reason where present. Elapsed time was excluded. This establishes a replay of the recorded outcome, not identity of every internal state or trajectory. Full trajectories were not retained. No training occurred in these sample attempts.

The audit checked code commits, tracked code bytes, artifact hashes, dependency-lock hashes, contract digests and seed lists. Fresh downloads of the Fashion-MNIST files and Concrete CSV matched their recorded hashes. The NetHack audit captured its retained image digest and runtime details; these were not in the original submitted manifest.

| Requirement | Current evidence | Missing guarantee |
| --- | --- | --- |
| Frozen experiment | Contract, evaluator digests, fixed seeds and result version are retained. | Normal downloads expose only the current package. Earlier results need their own versioned package export. |
| Code and evaluator | A full commit is required. Local fixtures have the matching code. | No accessible code snapshot is retained by the portal. Three task adapters are outside their ZIPs. |
| Predictions, policy or checkpoint | Reference and SHA-256 are recorded. Local bytes match. | The portal neither stores nor checks access to the artifact or associated model files. |
| Data and split | These sample contracts identify the source data or environment. Batch source hashes matched. | There is no general mandatory data-file manifest, immutable snapshot or structured split/generation record. |
| Environment | A dependency-file path and hash are recorded. Local files and installed versions were checked during this audit. | The portal does not retain the lock or verify installed packages. Python, OS, system libraries, drivers and image digest are not mandatory structured fields. |
| Commands and configuration | Generic runner, adapter entrypoint and prose protocol exist. | Exact preprocessing, training and prediction-generation commands/configs are not required. Local paths need documented relocation. |
| Randomness | Environment, Python and NumPy seeds are set by the Gym adapter. | Framework seeds, deterministic execution settings and custom-adapter RNG behavior are not checked generally. |
| Outputs and diagnosis | Per-seed scores, status and step counts are retained. | The runner discards process output and errors. Raw predictions, trajectories and logs are not required retained evidence. |
| Hardware and tolerance | Resource text and wall-time limits exist. | Actual hardware/software capture and numerical comparison tolerances are not mandatory. |
| Training | A nonempty provenance string is required. These samples correctly report no training. | A trained submission need not provide structured training data, configuration, seeds, logs, checkpoint selection or generation commands. |

A code commit alone also does not fully identify what ran. The runner checks tracked changes with `--untracked-files=no`, then imports from the researcher directory first. Untracked or ignored Python files can affect execution without changing that commit. Fresh-clone replays passed for these fixtures, so the audit found no such effect on these seven results.

The distinction between trust and preservation matters. Lite can trust lab researchers without running every submission independently. It still needs accessible, complete files before it can state that a result is reproducible. A hash identifies bytes; it does not preserve them or grant access to them. A lock-file hash also does not establish which dependencies were installed.

The general implementation change should provide one immutable reproduction bundle per result:

1. Preserve the exact challenge package, evaluator, seed list, manifest and submitted records, including older versions.
2. Store or reference lab-accessible code snapshots and all required artifacts. Verify access and content hashes. Local-only references can remain a draft state, but cannot establish complete materials.
3. Include data-file hashes, source/snapshot references, preprocessing, split or generation rules, and any additional model configuration/assets.
4. Retain an installable environment specification or retrievable image, with Python/system/framework versions, hardware details and execution commands.
5. Record all relevant RNG settings, logs/raw outputs and an agreed numeric tolerance. Bind these to the result version.
6. For trained methods, add training configuration, data versions, seeds, code, commands, logs and checkpoint-selection rules. Record no-training cases explicitly.
7. Check a new-directory replay using only the retained bundle and its declared accessible sources. Do not silently use files from a developer's working folder.

Keep separate evidence states: **reported**, **reproduction materials complete**, and **evaluation reproduced**. Record **training reproduced** separately when training was actually repeated. A local replay on the same retained runtime must not silently become independent reproduction. Full hosted verification remains separate from this Lite completeness check.

Code evidence: `lite.py` lines 78–84 accept local references; lines 519–569 validate and store metadata without fetching artifacts; lines 861–881 restrict downloads to the current package. `lite_runner.py` lines 89–105 check tracked code and local hashes; lines 123–146 discard execution output; lines 153–156 give the researcher directory import precedence. `lite_gym_adapter.py` lines 13–16 seed Python and NumPy.

Detailed evidence is saved under `autokaggle/test-results/lite-repro-audit-2026-11-05/`: `server-ledger.json`, the seven live saved records, batch and RL replay reports, and the NetHack comparison/runtime record. This directory is private test material and is ignored by Git. See also the [ZIP audit](LITE_ZIP_AUDIT_2026-11-05.md).

A live OpenRouter review used `openai/gpt-6.1-sol` at medium reasoning with the saved NetHack contract, source records and result context. The computed contract version was checked against the saved version before the call. The agent preserved the scientific protocol and correctly distinguished the reported local replay from independent evaluation and training reproduction. It identified missing file access and environment-transfer material. No proposal was applied to a live session. The final response is in `live-model-review.json`; the direct file checks and replays remain the primary evidence.
