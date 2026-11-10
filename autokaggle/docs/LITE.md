# BOLD AutoKaggle Lite

Lite is the internal ML research mode. Open `/lite`. On the separate Lite host, `/` also opens Lite. The original Full host retains the Full interview.

One accepted contract produces a private website preview, README, research ZIP, fixed seed list, result schemas, local runner, and result record. Lite supports supervised batch evaluation and interactive environments. It accepts predictions, a checkpoint, or a policy as the contract permits. It does not start hosted compute or rent nodes.

## Required workflow before merging Lite into main

**One evaluator repository per problem.** Keep the Lite agent in the AutoKaggle application repository. Each onboarded problem gets a separate GitHub evaluator repository accessible to its collaborators. Include the versioned YAML config, implemented scoring adapter, pinned environment, input contract, and instructions for required assets. Generate the YAML and the runner's configuration from the same accepted contract. A collaborator clones a pinned release, supplies a compatible checkpoint, policy, or output, and runs one documented command locally. The command returns the defined fitness and a machine-readable result. Test it on a known sample from a clean clone before marking the benchmark ready. The current ZIP runner is a starting point. Its generic adapter still requires implementation for tasks that have no packaged adapter.

**BOLD OS as the project home.** Collaborators start and resume Lite from BOLD OS. The Problem Bank holds the problem record and its status. Benchmarks links the problem to the evaluator repo and pinned version. Show incomplete work as a draft until the scoring test passes. Preserve the BOLD OS record IDs and repo ID so a retry updates the same records. Lite can supply the interview and build backend. The existing standalone preview is part of the current implementation and does not satisfy this requirement.

These are merge requirements. The current Lite implementation still needs evaluator repo provisioning, the clean-clone scoring check, and a write integration for the BOLD OS sections.

## Start a session

1. Start the existing app with `OPENROUTER_API_KEY` in the private environment file. Lite calls OpenRouter directly. The default model is `openai/gpt-6.1-sol` with medium reasoning. `AUTOKAGGLE_LITE_MODEL` can select another compatible model. Package generation is deterministic.
2. Open `/lite`. Create a session, enter the organizer email, and accept storage and model processing.
3. Add a public paper URL, a text PDF up to 16 MiB, a public GitHub repository, or both. Add the intended research question.
4. Review the proposed contract. Source excerpts, pinned revisions, suggestions, and extraction errors remain visible. Edit the proposal or ask for a correction. Select **Accept** to record it.
5. Answer only the remaining questions. The six groups are objective, source, artifact, evaluation, resources, and provenance. A scientific reference baseline is optional.
6. Build the package. Open its website preview, download the ZIP, and download the evaluation config. The config is the same `contract.json` included in the ZIP. It includes every required seed.
7. Run the package on the researcher's machine. Submit the generated `results.json` through the result control.

The model can propose many fields in one turn. It does not need a separate question for each field. An invalid field leaves other valid proposals available and becomes an open decision. Nothing becomes an accepted fact until the organizer confirms the proposal. Corrections create a new contract version. Previous packages become stale; saved results retain their original version.

A populated field can still contain an open decision. The model records each such decision and its reason. The proposal and checklist show these reasons. **Save defined details** records partial progress, but does not permit a package build. A model must supply a corrected field and an explicit resolution reason to close a saved gap. An organizer can also edit that field. Changes to unrelated fields do not clear it. The optional reference baseline never blocks a build. A new accepted review requires a package rebuild, even if the experiment values remain the same. Rebuilding unchanged values keeps the same seeds.

Each round permits 30 model calls. A provider failure preserves messages, accepted facts, and retrieved sources. **Retry** does not duplicate a message. A restart marks active work interrupted and permits retry. Researchers can resume or delete sessions.

The revision agent receives the latest three saved result summaries, their versions, checks, and evidence limits. It can discuss failures and requested changes without repeating the initial interview. It does not receive raw artifacts or private artifact references through this result context.

## Internal access

In private deployments, set `AUTOKAGGLE_LITE_MEMBERS` to a comma-separated list of approved lab email addresses. A verified email alone does not establish lab membership. The list is empty by default; private Lite access then requires an administrator session. Ownership and collaborator checks still apply. Local development uses the existing local owner cookie.

Do not expose a server with private mode disabled. Lite does not silently convert Full sessions. Full model and dataset routes reject Lite project IDs. Full and Lite session lists are separate.

## Contract and adapters

The contract separates task kind, artifact type, metric, source version, input/output interface, training policy, and evaluation limits. Resource notation can use GPU-hours, hardware and time, dollars, tokens, or another explicit bound. Batch metrics are means across the declared seeded runs. Seeds do not establish statistical independence: a contract must state whether they change sampling, execution order, or another condition. Environment metrics use one record per episode.

The local runner calls this adapter interface:

```python
evaluate(seed, manifest, contract) -> {
    "seed": seed,
    "status": "completed",  # or failed, timeout, truncated
    "score": measured_score,
    "steps": measured_steps,
}
```

The included `gym_adapter:evaluate` supports Gymnasium. The contract supplies `env_id`, optional imports and `gym.make` arguments, the success information key, and the reset method. `reset` calls `reset(seed=seed)`. `core_disp` calls `seed(core=seed, disp=seed, reseed=False)` before reset. No environment name is hardcoded. A policy loader receives the artifact path and returns an object with `act(observation)` and optional `reset()`.

For a task with a defined finite horizon, accept `horizon_policy: fixed_horizon` and a positive `max_steps`. Reaching exactly that number of steps completes the evaluation and scores its accumulated return. Early environment truncation and wall-time limits remain failures. The default `require_termination` requires natural termination and treats a step-limit stop as incomplete. Result records preserve the end reason. Select this policy from the scientific protocol, not from the score it produces.

For another environment or a batch dataset, implement the declared adapter in the researcher repository. The generated `adapter.py` is an interface template. It raises an error until implemented. Template generation is not an execution test.

Each manifest binds the challenge version and contract digest to a code commit, artifact SHA-256, dependency-lock SHA-256, loader, training provenance, and resource record. Local references such as `local:checkpoint.bin` are accepted as metadata. Researchers do not need to publish private checkpoints. The service never opens local references.

The runner checks the local artifact and dependency hashes, contract digest, and tracked Git revision before execution. Each seed starts a fresh process. Per-run and total wall-time limits apply. Seeds that cannot start before the total limit remain timeout records. No failed run may be omitted. Zero contribution is allowed only for success and accuracy; other metrics require an incomplete run on failure.

The runner is for trusted code. It is not a security sandbox, GPU quota service, or proof that installed packages match a clean build. A dependency lock records an environment; a controlled rebuild is needed for independent reproduction.

## Evidence and limits

- **researcher_reported:** a local result before server checks.
- **evidence_checked:** the server checked the version, contract digest, provenance fields, seed coverage, score bounds, and failure rules. It did not retrieve the artifact, check repository bytes, or run the experiment.
- **independently_reproduced:** reserved for a separate controlled run. This implementation cannot grant that status from submitted metadata.

Fixed seeds are visible in the package. This is not blind evaluation. Dataset availability and answer exposure are separate fields. Reproduction of an evaluation score does not prove the reported training method, cost, or data use. Do not describe an internal smoke test as scientific baseline reproduction.

The [submitted-result audit](LITE_REPRODUCTION_AUDIT_2026-11-05.md) replayed seven sample reports from retained local files. It also found that the portal does not retain a complete reproduction bundle or check that another lab member can retrieve the required files. `evidence_checked` must not be presented as a complete-materials or reproduction guarantee.

Limits: public imports only; twelve source records; bounded PDF extraction; twelve repository files from a fixed commit; five aggregate metrics; 10,000 seeds and 100 saved result bundles per session. Repositories are read, never executed. Dataset links are references, not downloads. Independent verification, GPU execution, and BOLD OS compute approval remain separate work.

Lite deliberately differs from a Kaggle competition. It uses visible seeds and researcher-run evidence for trusted lab experiments. Full private-answer checks and public submission controls remain separate.

## API

All endpoints retain owner access checks and same-origin writes.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/lite/projects` | List accessible internal sessions. |
| `POST /api/lite/projects` | Create with `organizer_email`, `storage_accepted: true`, optional `title`. |
| `GET /api/projects/{id}/lite` | Read messages, contract, proposal, checklist, sources, package, results. |
| `POST .../lite/import` | Queue extraction with `request_id`, optional `paper_url`, `repository_url`, `brief`. |
| `POST .../lite/paper` | Upload a PDF through multipart field `file`. |
| `POST .../lite/message` | Queue a turn with `request_id` and `message`. |
| `POST .../lite/retry` | Retry saved failed work with a new `request_id`. |
| `POST .../lite/continue` | Start another round after 30 calls. |
| `POST .../lite/accept` | Accept `proposal_id`, with optional edited `contract`. |
| `POST .../lite/discard` | Discard `proposal_id`. |
| `POST .../lite/build` | Build with `request_id`. |
| `GET .../lite/package` | Download current ZIP. Stale artifacts return 409. |
| `GET .../lite/config` | Download the matching `contract.json`, including all fixed seeds. Stale artifacts return 409. |
| `GET .../lite/preview` | View the private website template. |
| `GET .../lite/readme.md` | Download the README. |
| `POST .../lite/results` | Submit `request_id`, `manifest`, and all `results` records. |
| `DELETE /api/projects/{id}` | Delete with `confirm: true`. |

Queued requests return immediately. Poll the state endpoint while status is `working`. Repeated request IDs reuse the saved action. An ID with different input returns 409. Result retries reuse the saved result. A run that finishes after a revision can still submit evidence for its known built version. The service uses that version's frozen contract and marks the result historical. It does not score old evidence with new settings.
