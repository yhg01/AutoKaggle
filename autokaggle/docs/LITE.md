# BOLD AutoKaggle Lite

Lite is the internal ML research mode. Open `/lite`. On the separate Lite host, `/` also opens Lite. The original Full host retains the Full interview.

One accepted contract produces a private website preview, README, research ZIP, fixed seed list, result schemas, local runner, and result record. Lite supports supervised batch evaluation and interactive environments. It accepts predictions, a checkpoint, or a policy as the contract permits. It does not start hosted compute or rent nodes.

## Required workflow before merging Lite into main

**One evaluator repository per problem.** Keep the Lite agent in the AutoKaggle application repository. Each onboarded problem gets a separate GitHub evaluator repository accessible to its collaborators. Include the versioned YAML config, implemented scoring adapter, pinned environment, input contract, and instructions for required assets. Generate the YAML and the runner's configuration from the same accepted contract. A collaborator clones a pinned release, supplies a compatible checkpoint, policy, or output, and runs one documented command locally. The command returns the defined fitness and a machine-readable result. Test it on a known sample from a clean clone before marking the benchmark ready. The current ZIP runner is a starting point. Its generic adapter still requires implementation for tasks that have no packaged adapter.

**BOLD OS as the project home.** Collaborators start and resume Lite from BOLD OS. The Problem Bank holds the problem record and its status. Benchmarks links the problem to the evaluator repo and pinned version. Show incomplete work as a draft until the scoring test passes. Preserve the BOLD OS record IDs and repo ID so a retry updates the same records. Lite can supply the interview and build backend. The existing standalone preview is part of the current implementation and does not satisfy this requirement.

These are merge requirements. The evaluator build and its clean-clone scoring check are implemented for local use; see **Build evaluator** below. Evaluator repository publishing on GitHub and a write integration for the BOLD OS sections are still needed.

## Build evaluator

After a contract is accepted, **Evaluator → Build evaluator** produces a tested evaluator release for that exact contract version. It publishes nothing. See the [10 November build record](LITE_EVALUATOR_BUILD_2026-11-10.md) for what has and has not been tested.

1. **Freeze.** The build reads the frozen `contract.json` of the current package and binds to its version and digest. It derives the metric direction: `success_rate`, `accuracy`, and `mean_score` are maximized; `rmse` and `mae` are minimized. A local-only source, private scoring targets, or a reserved adapter module name stops the build with a named decision before any model call.
2. **Implement.** A coding agent (opencode, pinned in `deploy/lite-build.Dockerfile`) works in a disposable workspace. It writes the task adapter, an artifact loader for policies and checkpoints, `requirements.lock`, `assets.json`, three example artifacts, their expected scores, and a separate calculation of those scores. It must report a blocker instead of inventing a decision that affects scoring. The instructions are in `prompts/lite_build.md`.
3. **Isolate.** The agent runs in a non-root container with no added capabilities and bounded CPU, memory, processes, and time. It receives a one-build token for a loopback gateway (`lite_gateway.py`). The gateway holds the provider key, allows only the configured model, sets the reasoning level, and caps the number of requests. Application, GitHub, and provider credentials never enter the container. Outbound network stays open for package and asset downloads.
4. **Assemble.** The application builds the release itself. It takes only publishable agent files: top-level Python modules, `requirements.lock`, `assets.json`, `NOTES.md`, and `fixtures/`. It rejects links, large files, unpinned requirements, non-HTTPS assets, and a score calculation that imports the evaluator. It writes `evaluate.py`, `run.py`, `gym_adapter.py`, and `fetch_assets.py` from its own source, plus `README.md`, `evaluation.yaml`, the unchanged `contract.json`, and `evaluator.lock.json` with a SHA-256 for every file. The YAML and the runner's `contract.json` come from the same accepted contract.
5. **Test from a fresh clone.** The candidate commit is cloned in a second clean container. Only `requirements.lock` is installed, into a new virtual environment. Declared assets are downloaded and verified. The test then runs the separate score calculation, scores the valid and the wrong example and compares each with its expected score, requires the wrong example to score worse, requires the invalid artifact to receive no score, and confirms that scoring left the checkout unchanged.
6. **Release.** Only a passing clone test makes the build ready. The commit becomes `main` and receives the tag `v<N>`. Earlier releases stay in the repository. The build record binds the commit, contract version and digest, file lock, test report, runtime, model, and request count. A contract change makes the release stale; a new build is required. Failed and blocked builds stay drafts and show their cause.

A collaborator downloads the release as a Git bundle, then runs:

```sh
git clone evaluator.bundle evaluator && cd evaluator && git checkout v1
python -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.lock
python fetch_assets.py
python evaluate.py --artifact PATH --output results.json
```

The last output line is JSON with `fitness`. `results.json` uses the existing Lite result format and can be uploaded through the results control. `evaluate.py` refuses a release file that differs from the lock, a missing asset, and a directory that is not a Git clone.

Limits of this version:

- Expected scores are established by a separate calculation written in the same build job. This is a consistency check with a written basis, not an independent party. Review each example's basis. A researcher-supplied reference example is not yet supported.
- The container is not a security boundary against a determined attacker, and its network is open. Builds are for trusted lab contracts.
- Builds need Docker on the application host. The hosted Lite pod has no Docker, so the build control reports that builds are unavailable there. `AUTOKAGGLE_LITE_BUILD_RUNTIME=local` runs the agent as a host process for development only.
- Dependencies install as wheels only unless `AUTOKAGGLE_LITE_BUILD_ALLOW_SDIST=1`. An artifact is one file. The five contract metrics are unchanged.
- Settings: `AUTOKAGGLE_LITE_BUILD_MODEL` (default: the selected provider's Lite model), `AUTOKAGGLE_LITE_BUILD_EFFORT` (`medium`), `AUTOKAGGLE_LITE_BUILD_MINUTES` (30), `AUTOKAGGLE_LITE_BUILD_REQUESTS` (150), `AUTOKAGGLE_LITE_BUILD_CPUS` (2), `AUTOKAGGLE_LITE_BUILD_MEMORY_GB` (4), `AUTOKAGGLE_LITE_BUILD_CONCURRENCY` (1).

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

## Model provider

`AUTOKAGGLE_LITE_PROVIDER` selects the model service for both the interview and the evaluator build. Set it at startup.

| Value | Key | Default model | Notes |
| --- | --- | --- | --- |
| `openrouter` (default) | `OPENROUTER_API_KEY` | `AUTOKAGGLE_LITE_MODEL`, else `openai/gpt-6.1-sol` | The interview is the unchanged call in `lite.py`, with strict schema output. |
| `deepseek` | `DEEPSEEK_API_KEY` | `AUTOKAGGLE_LITE_DEEPSEEK_MODEL`, else `deepseek-v4-pro` | DeepSeek has JSON output without a strict schema. The schema is placed in the prompt and one blank reply is retried. |

Both routes send the same interview context and pass the same `parse_proposal` validation. The DeepSeek route lives in `lite_providers.py` and is installed at startup, so `lite.py` stays byte-identical and existing contract versions and seeds do not change. Medium reasoning maps to DeepSeek's `high`. For builds, the gateway forwards to the selected provider and the coding agent returns DeepSeek's reasoning text on later tool-call turns, as that API requires. The session view's model label in `lite.py` still names the OpenRouter model; each proposal and build record states the model that actually answered. Record the provider and model with every live test.

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
| `GET .../lite/evaluator` | Read the evaluator status, the current tested release, the last build's blockers, cause, and tests. |
| `POST .../lite/evaluator/build` | Start a build with `request_id`. Prepares the package first if needed. 503 when builds are unavailable. |
| `GET .../lite/evaluator/bundle` | Download the tested release as a Git bundle. 409 unless a release matches the current contract. |
| `GET .../lite/evaluator/config` | Download the release's `evaluation.yaml`. |
| `GET .../lite/evaluator/readme.md` | Download the release's README. |
| `DELETE /api/projects/{id}` | Delete with `confirm: true`. |

Queued requests return immediately. Poll the state endpoint while status is `working`. Repeated request IDs reuse the saved action. An ID with different input returns 409. Result retries reuse the saved result. A run that finishes after a revision can still submit evidence for its known built version. The service uses that version's frozen contract and marks the result historical. It does not score old evidence with new settings.
