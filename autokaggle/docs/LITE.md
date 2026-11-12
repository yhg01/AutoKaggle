# BOLD AutoKaggle Lite

Lite is the internal ML research mode. Open `/lite`. On the separate Lite host, `/` also opens Lite. The original Full host retains the Full interview.

One accepted contract produces a private website preview, README, research ZIP, fixed seed list, result schemas, local runner, and result record. Lite supports batch evaluation, interactive environments, optimization, forecasting, generation, and custom evaluation. It accepts the artifact defined by the contract. Researchers run their experiments locally. The service can prepare and test a small evaluator in a bounded build job; it does not rent nodes.

## Required workflow before merging Lite into main

**One evaluator repository per problem.** Keep the Lite agent in the AutoKaggle application repository. Each onboarded problem gets a separate GitHub evaluator repository accessible to its collaborators. Include the versioned YAML config, implemented scoring adapter, pinned environment, input contract, and instructions for required assets. Generate the YAML and the runner's configuration from the same accepted contract. A collaborator clones a pinned release, supplies a compatible checkpoint, policy, or output, and runs one documented command locally. The command returns the defined fitness and a machine-readable result. Test it on a known sample from a clean clone before marking the benchmark ready. The current ZIP runner is a starting point. Its generic adapter still requires implementation for tasks that have no packaged adapter.

**BOLD OS as the project home.** Collaborators start and resume Lite from BOLD OS. The Problem Bank holds the problem record and its status. Benchmarks links the problem to the evaluator repo and pinned version. Show incomplete work as a draft until the scoring test passes. Preserve the BOLD OS record IDs and repo ID so a retry updates the same records. Lite can supply the interview and build backend. The existing standalone preview is part of the current implementation and does not satisfy this requirement.

These are merge requirements. The evaluator build and its clean-clone scoring check are implemented for local use and the configured Internal Civo build service; see **Build evaluator** below. Publishing a tested release to a private GitHub repository is implemented; see **Publish to GitHub**. Automatic publication uses the configured BOLD GitHub connection. Project access lists and a write integration for the BOLD OS sections remain separate work.

## Build evaluator

After a contract is accepted, **Evaluator → Build evaluator** produces a tested evaluator release for that exact contract version. On the configured Civo Lite service, a successful build automatically publishes the tested commit to a private BOLD GitHub repository. See the [10 November build record](LITE_EVALUATOR_BUILD_2026-11-10.md) for what has and has not been tested.

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

## Publish to GitHub

Automatic publication starts only after all release checks pass. Failed builds create no repository. Each problem keeps one repository; tested updates add `v1`, `v2`, and later tags. A failed or interrupted publication keeps the tested local release available. Retry checks the remote state and reuses the same repository. An older contract is never published as the current release. Existing sessions are not published in bulk when this setting is enabled.

With `AUTOKAGGLE_LITE_AUTO_PUBLISH=1`, a successful evaluator check automatically publishes the tested release for the current contract to a private repository for that problem. The dialog shows publication progress, the repository link, and a ZIP download pinned to the tested commit. **Retry publication** retries a failed push without another build. Services with automatic publication disabled retain **Evaluator → Publish to GitHub**. It is available when `AUTOKAGGLE_LITE_GITHUB_OWNER` names the account or organization that holds evaluator repositories and the server has a usable GitHub credential.

- **One repository per problem.** The name is `lite-eval-<title>-<first eight characters of the problem ID>`. It is fixed at the first build and does not follow later title changes. The repository ID and URL are saved on the problem before the push, so a retry reuses the same repository.
- **The tested commit, unchanged.** The push carries `main` and the `v<N>` release tags in one all-or-nothing push, without force. Afterwards the application reads the refs back from GitHub and requires the tested commit.
- **Private only.** A new repository is created private. The application refuses to push to a repository that is not private.
- **Nothing is overwritten.** A repository of the same name that was not created for the problem is refused. So is a repository whose `main` or release tags were changed outside the application.
- **A removed repository is not replaced silently.** Publishing reports the saved repository as missing. `POST .../lite/evaluator/publish` with `{"new_repository": true}` creates a fresh one. Use it only when the saved repository was removed on purpose.
- **The release names its repository.** A release built while an owner is configured records the repository address in `evaluator.lock.json` and in its README, and result files carry it as `code_repository`. A release built earlier records `local:evaluator-release`. It can still be published unchanged; the dialog states the gap. Rebuild to record the address.

There are two ways to reach GitHub. The application picks one at start.

- **A developer machine: the `gh` login.** The application runs `gh api` and lets `gh` answer Git's credential request for the one push. It never reads the token.
- **A server: `AUTOKAGGLE_LITE_GITHUB_TOKEN`.** When this is set, the application calls the GitHub API over HTTPS and pushes with the `dulwich` library. It starts no `git` or `gh` program, so it works in the hosted pod, which has neither. Use a fine-grained token whose resource owner is the evaluator organization, with repository access "All repositories" and the repository permissions Administration (read and write) and Contents (read and write). A token that awaits organization approval is reported as GitHub's refusal when publishing is tried.

In both cases the build container never receives the credential, and no error text includes it. The token client refuses a rewritten `main` itself, because a Git server would accept one.

For hosted Lite, the deployer reads the token from the private file `$HOME/.config/autokaggle/lite-github.env` and places it only in the `lite-secrets` Secret. `deploy --github-owner NAME` sets the owner in `lite-config`; the owner is kept on later deployments unless the option is given again. See [the deployment record](../deploy/LITE_WEB.md). A personal login with access to unrelated repositories must not be placed on a shared server.

Limits of this version:

- Hosted builds require the Internal Kubernetes runtime described in `deploy/LITE_WEB.md`. Admission follows the configured Lite access policy. They do not run researcher training jobs.
- Repository access follows GitHub organization and repository permissions. Lite does not add collaborators automatically. Email access to Lite does not grant access to a private GitHub repository.
- The lab-approved repository template and its project-tracking files are not applied.
- BOLD OS Problem Bank and Benchmarks records are not written.
- After a repository is transferred or renamed, publishing follows it by ID. Earlier releases keep the old address in their lock file.

## Start a session

1. Configure a model provider in the private environment. The 12 November rollout uses `DEEPSEEK_API_KEY`, `AUTOKAGGLE_LITE_PROVIDER=deepseek`, and `deepseek-v4-pro`. OpenRouter remains supported. Package generation is deterministic.
2. Open `/lite`. Create a session, enter the organizer email, and accept storage and model processing.
3. Describe the research question. Paste a public paper or GitHub link in chat, or use **Attach** for multiple files. Documents, tables, text, code, and images are accepted. Each file is limited to 50 MiB; image interpretation is limited to 20 MiB. Images are interpreted by a model and need review. The earlier Sources dialog retains its 16 MiB PDF limit.
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

The owner approved temporary verified-email access on 12 November 2026, pending BOLD OS sign-in. Set `AUTOKAGGLE_LITE_ACCESS_POLICY=verified_email` for this mode; users still sign in with an email code and retain private project ownership. The Slack/BOLD OS replacement is specified in [the sign-in plan](LITE_BOLD_OS_AUTH_PLAN.md).

With the default `AUTOKAGGLE_LITE_ACCESS_POLICY=members`, set `AUTOKAGGLE_LITE_MEMBERS` to a comma-separated list of approved lab email addresses. A verified email alone does not establish lab membership. The list is empty by default; private Lite access then requires an administrator session. Ownership and collaborator checks still apply. Local development uses the existing local owner cookie.

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
| `POST .../lite/evaluator/publish` | Push the tested release to the problem's private GitHub repository. Optional `new_repository`. 409 without a tested release, 503 when publishing is unavailable, 502 with the cause when GitHub or a safety check refuses. |
| `GET .../lite/evaluator/bundle` | Download the tested release as a Git bundle. 409 unless a release matches the current contract. |
| `GET .../lite/evaluator/config` | Download the release's `evaluation.yaml`. |
| `GET .../lite/evaluator/readme.md` | Download the release's README. |
| `DELETE /api/projects/{id}` | Delete with `confirm: true`. |

Queued requests return immediately. Poll the state endpoint while status is `working`. Repeated request IDs reuse the saved action. An ID with different input returns 409. Result retries reuse the saved result. A run that finishes after a revision can still submit evidence for its known built version. The service uses that version's frozen contract and marks the result historical. It does not score old evidence with new settings.

## Server repository imports

Public GitHub links create an immutable source snapshot on the server. The agent can read files and search that snapshot. It does not run repository code during import. The snapshot records the commit and each file digest. It excludes Git history, submodule downloads, and Git LFS downloads; missing assets remain explicit requirements.

Imports allow up to 256 MiB compressed, 1 GiB extracted, 40,000 files, and 128 MiB per file. Each session can store six revisions. The service checks free space before download. Unsafe archive paths are rejected. Links and special files are omitted. Failed imports clean their temporary files. Deleting a session removes its stored snapshots. Source excerpts in model prompts remain bounded; a local file-search tool supplies further details.

## Conversation and task-specific requirements

The agent asks for missing decisions in chat. Secondary functions are in **Session tools**. Once the relevant step is ready, the chat shows the package, evaluator, or result action. Custom scores require a metric name, exact definition, and direction. Optimization requires constraints. Forecasting requires a time and leakage policy. Generation requires a reference and sample policy. Environment tasks retain episode, seed, and termination requirements. These additions do not relax Full's execution or private-answer controls.

### Downloaded evaluator ZIP

The GitHub ZIP of a new release can run without a Git checkout. `revision.txt` uses Git's [archive substitution](https://git-scm.com/docs/gitattributes#_export_subst) to record the release commit. The scorer checks the release file digests before execution. The revision is provenance metadata, not a signature or proof of independent reproduction. The generic researcher-code runner still requires a clean Git checkout; the archive option applies only to a complete evaluator release with its matching lock and contract.

## Administrator logs — 12 November 2026

Open `/internal` on the Lite service with administrator access. Select a project.

- **Conversation** shows the saved Lite messages in their original order.
- **Model calls** shows newly recorded interview requests, responses, tool calls, duration, and token use. Select **Input** for the request and system instructions. An interview turn can include several model requests. The project list shows interview turns separately.
- **Saved fields** separates the accepted contract from the current proposal. **Changes** shows accepted contract revisions.
- **Execution** shows build status, errors, checks, and submitted results. Select a build, then **Agent log** or **Test log**. Running Civo jobs save log snapshots about every ten seconds. Click the log button again to load the latest snapshot. A pending pod or model response can have no output yet.
- **Draft & artifacts** shows source records, packages, evaluator releases, and publication records. **Export** downloads the same redacted snapshot; build log text is loaded separately.

Earlier Lite interviews did not save provider request/response records. Their saved messages and build records remain available. Do not infer historical request counts from the interview turn count. Missing model responses cannot be recovered.

The service retains the latest 30 interview request records per project. Each text field is capped at 24,000 characters and marks truncation. The log viewer returns the latest 256 KiB of each saved build log. Credentials and email addresses are redacted. Hidden model reasoning is not saved by Lite. These diagnostics require administrator access and do not enter participant packages.
