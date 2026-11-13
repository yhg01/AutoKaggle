# Lite evaluator quality and release review

An evaluator is a software release. A scalar score from one example does not establish that it implements the accepted contract.

## Release checks

1. The planning call reads the complete accepted contract. It writes atomic requirements with exact source quotations in `quality.json`. Every nonempty contract field must be represented. The server freezes this plan before code generation.
2. The coding call implements the evaluator and its tests. `coverage.json` maps requirements to actual unittest IDs. Tests must cover applicable secondary metrics, outputs, input constraints, reference identity, resource rules, and failures. Every mapped test must execute and pass. A skipped or nonexistent test cannot count as coverage.
3. A separate model call reviews the contract, implementation, fixtures, and assertions. It uses a fresh conversation. It reports findings without editing the files. Up to two review passes share the existing build time and model allowance. Unresolved findings keep the release in draft.
4. The service assembles the repository from bounded code contributions and trusted runner files. A clean clone installs its pinned dependencies and executes the scoring examples and the requirement tests. It records the exact commit and measured results.
5. The organizer gets a recorded review invitation. The session shows the software checks separately from validation on research data. Legacy releases remain unassessed under the new checks.

A model review can miss a defect. Test coverage proves that named tests ran; it does not prove that their assertions express the science correctly. A copied-reference example is a zero-distance sanity check. It must not be presented as research validation.

## Result bundle and large assets

`evaluate.py` accepts `--mode synthetic` or `--mode research` (the default). The adapter receives the mode and a durable output directory. Required scalar metrics must be finite. Required output files must exist inside that directory. Results record their names, byte counts, hashes, and the selected reference identity. Keep the output directory with `results.json` when sharing a result.

Use `--reference PATH` for a local reference file or directory. Licensed data stay outside Git. An asset declaration can identify local research data and its digest. If the data are not available at build time, the adapter must ask for them in research mode. It must not fall back to synthetic reference data.

The runner can hash files and directory inputs without reading each file into memory. Directory hashes use the `bold.directory.v1` manifest format in `quality_checks.py`. Archives must reject unsafe paths, links, duplicate entries, and expansion beyond the declared allowance. Code and small test fixtures retain their separate publication limits. These limits do not define a maximum research artifact size. Available disk, memory, and time still apply. The service does not add storage or compute when a run exceeds those limits.

The ordinary result portal checks reported evidence and saves it. It does not turn a researcher-supplied report into an independently validated run.

## Research-data validation and approval

The organizer supplies a retrievable artifact, its byte count and SHA-256, and an independently established expected fitness with its basis. A separate reference link can point to a file or bounded archive. This is optional for tasks where the artifact contains the declared evaluation input. Use a private local scoring run when licensed data cannot be made available to the service; that run remains researcher-reported until a controlled service check is possible.

The service obtains the declared files with its existing URL and address checks. It checks storage before import. A bounded job clones the pinned evaluator and executes it in research mode. The report binds the observed and expected fitness to the input hashes, contract, evaluator commit, resources, and result file. A mismatch keeps validation failed. The organizer must then approve that exact commit and research report. A new validation run or a scientific change invalidates the old approval for registration.

This check verifies execution against declared assets and an expected result. It does not prove that the reference is scientifically appropriate, that training avoided exposed answers, or that a locally modified evaluator is trustworthy. Those limits remain visible.

## Coding iteration

The review email opens the saved session in evaluator review mode. **Revise code in chat** uses the normal chat box. The next coding job starts from the last tested commit and, when available, the saved failed draft. It receives the feedback, recent conversation, previous tests, failure, and review findings. **Build evaluator** also resumes a saved draft and its review context. A queue failure records a clear error and releases the session for another attempt. It does not discard an earlier draft. Failed drafts retain bounded code files; they do not retain downloaded data, credentials, or dependency caches.

The new release repeats the checks. Earlier commits and tags remain available. A change to scientific meaning must return to the scientific interview and require acceptance before rebuilding. Email send status is recorded. An uncertain delivery needs an explicit retry after checking the inbox.

A coding revision reuses the frozen requirement plan only when its contract digest still matches. This preserves requirement IDs and avoids unnecessary planning. A failed or incomplete review keeps the code in draft. The interface reports when the time or request allowance ended. File searches stay within the evaluator workspace. Long scoring commands remain bounded by the remaining job allowance.

## BOLD OS registration

The release can enter the registration queue when the accepted contract matches the tested release, the build and contract coverage pass, software review and synthetic checks pass, and the exact commit is published on GitHub. A specific BOLD OS project link is required. BOLD OS verifies that the project exists. Paper and repository links cannot substitute for that project.

The Problem Bank shows three evidence stages: **Fully implemented**, **Checked**, and **Validated on the actual task**. Known-score, invalid-submission, and clean-clone checks are required for Checked. Only a controlled check on the declared research assets can establish Validated. Human approval is recorded separately and must name the exact validated commit and report. Earlier stages can be listed without implying research validation or human approval.

The queue uses one stable AutoKaggle session identity. Its idempotency key covers the complete registration payload. Project, evidence, approval, or metadata changes get a new receipt while updating the same Problem Bank entry. Earlier evaluator releases remain available within that entry. There is no separate Benchmarks page.

Configure `AUTOKAGGLE_BOLD_REGISTRY_URL` and `AUTOKAGGLE_BOLD_REGISTRY_TOKEN` in private server configuration after the BOLD OS registry PR is reviewed and deployed. The endpoint is `https://europe-west2-bold-d7ff2.cloudfunctions.net/boldApi/v1/register_benchmark`. The adapter permits only that HTTPS endpoint and does not follow redirects. A read-only MCP token cannot register records.

The POST body is `{ "registration": <record> }`, using `bold.autokaggle.registration.v1`. It includes the BOLD project ID and optional board, `destinations: ["problem_bank"]`, objective, task, evaluator links, checks, descriptive metadata, and the full/Lite session type. Research evidence and human approval are included when present. The approved acting token goes in the Authorization header. A successful receipt must match `problem_id`, `benchmark_id`, `commit`, and `idempotency_key`. Partial receipts, connection errors, and permission denials remain retryable.

The companion BOLD OS branch is `codex/problem-bank-benchmarks`. Its legacy release collection and endpoint names remain for compatibility. The page includes resume and handoff-management links. Handoff codes remain in AutoKaggle: only the owner can create or revoke a code, and the recipient must sign in and explicitly accept session access. The bank does not store a bearer code.

Verification on 13 November used the local Firebase demo service. The real sender registered a checked fixture, retried without duplication, and updated the same record with synthetic research evidence. This proves transport and state handling, not validation of research data. The live project-question test used DeepSeek V4 Pro, not OpenRouter.

## Coding harness

Keep OpenCode with the configured DeepSeek model for this change. The verified fault was incomplete acceptance coverage. A harness replacement does not fix that fault. The current OpenCode runtime is pinned to 1.19.5. DeepSeek Harness is a separate implementation choice and needs a controlled comparison before migration.

The official DeepSeek Harness README still marks it as a developer preview with expected compatibility changes (checked 12 November 2026). No comparison run has established a quality gain for these evaluator tasks. A later comparison should use the same contracts, assets, model, budget, and independent acceptance tests. Compare completed releases, missed requirements, revision success, cost, and elapsed time.

References: [OpenCode agents](https://opencode.ai/docs/agents/), [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness).
