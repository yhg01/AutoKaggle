# AutoKaggle: downstream research backend

This document gives the next implementation steps. The current MVP includes onboarding, deterministic data checks, a development baseline, and private website and package drafts. It also supports prediction submission quotas and organizer review links. See [API.md](API.md) for delivered endpoints. The private review service is deployed on Civo with HTTPS, access control, and persistent storage. See the [deployment record](../deploy/WEB.md) and restart check (local operational record; not included in this repository). Gmail API sending and email-code sign-in are deployed over HTTPS. Real receipt, account access, logout, and return-session checks passed; see the email verification record (local operational record; not included in this repository). Delivery to other mail providers and a real organizer review invitation still need checks. Public launch remains deferred. See the [runner record](../deploy/README.md) for code execution status and cluster checks.

## Selected MVP delivery order

The owner selected survey types 1, 2, 3, 5, and 7 on 29 October 2026. The sequence below takes priority over the broader research extensions later in this document. It records planned work; it does not enable these features.

1. **Complete classic prediction and hidden-input code (1 + 2).** Reuse the existing submission ledger and isolated runner. Add immutable challenge versions, the configured split policy, hidden leaderboard membership, combined prediction submissions, final-entry selection, deadline enforcement, and private-score release. Retain the actual prediction files, code, required assets, and environment identifiers in private persistent storage. Hashes and scores alone cannot support final selection or reruns. The organizer must be able to review a complete first trial. Verify that retries and restarts preserve artifacts, quota, and final selections, and that private results cannot influence selections before close.
2. **Add optimization (7).** Start with one bounded candidate-file format and a versioned deterministic evaluator. Validate constraints before computing the objective. Record minimize/maximize direction and numeric tolerances. Verify a known feasible baseline, an improved candidate, invalid candidates, and consistent repeated scoring. Keep organizer-provided executable evaluators isolated and subject to review before use.
3. **Add inference API code (3).** Extend the runner with a local request/response protocol. The trusted controller supplies the next permitted batch only after the current response passes validation. Do not mount the full future input stream in the worker. Define state, ordering, limits, timeouts, and restart behavior. Verify malformed responses, timeouts, and denied access to later inputs using actual runner execution.
4. **Add live forecasting / future data (5).** Reuse the frozen code artifacts and batch or sequential runner. Start with one organizer-controlled data upload or supported source, with timestamp and version records. Record the submission cutoff, collection window, outcome availability, revisions, and score-release rule. Prevent source changes from silently changing a scored dataset. Verify late data, missing outcomes, source failure, correction handling, and restart recovery. A historical replay proves only the workflow mechanics. A live acceptance run must freeze an entry before its later evaluation data become available.

All four steps use the same onboarding chat, website template, research ZIP, budget record, daily allowance, submission history, and private organizer review. Keep submission format, evaluator type, and holdout policy as separate configuration fields. Other survey types and the broader autonomous research loop are deferred. Test work must include live OpenRouter validation under [AGENTS.md](../../AGENTS.md), plus actual execution checks for the affected evaluator.

## Private review service deployment

The private web service is now deployed on the AutoKaggle Civo cluster. It has HTTPS, email accounts with separate workspaces, an administrator fallback, scoped review sessions, and persistent storage. See [the deployment record](../deploy/WEB.md). The local development command still binds to localhost. Gmail send-only OAuth is configured and verified for sign-in mail to the sender Gmail inbox. The restricted hosted code controller, off-cluster backups, and the public competition release flow remain separate work. Before broader use, verify the remaining request and queue limits under concurrent load.

The invitation flow and submission-only token checks are implemented. Review invitations use the tested Gmail transport and have automated coverage, but no real invitation was sent in the email sign-in verification run. Legacy administrator-owned drafts remain separate from the new email accounts. The deployed acceptance record covers the tested website, package, prediction submission, and scoped access paths. A reachable private review host is separate from a public competition launch.

Use the [Challenge design roadmap](https://data.mlr.press/assets/pdf/v02-10.pdf) for challenge decisions. Use AIRS-Bench's separation of task description, data preparation, and evaluation as an interface reference. Do not claim AIRS-Bench compatibility until an adapter passes execution tests. [AIRS-Bench repository](https://github.com/facebookresearch/airs-bench)

## 1. Freeze a reviewed task

Create an immutable task version from the approved onboarding record. Include the source-data hash, split membership, allowed columns, label definitions, metric version, prediction interface, data permissions, and resource estimates. Keep holdout membership and private source information in the organizer record. A change to data, target, metric, or split creates a new version and invalidates dependent results.

**Acceptance:** repeat preparation produces identical partition content. Prediction packages can contain test inputs, but never private answers or leaderboard membership. Code packages contain only approved training data and examples. Changing an evaluated input changes the task version. A reviewer can trace every public claim to a recorded decision.

## 2. Add a durable run controller

A run binds one task version, agent configuration, environment image, random seed, and budget. Store state transitions and artifacts outside the worker. Use explicit states: queued, running, waiting for review, stopped, failed, complete. Each action has an identifier, so a retry can recover its prior result.

Record planned and measured compute costs separately. Reserve model-call budget before sending a request. Count uncertain provider outcomes until reconciled. Preserve model usage and the pricing configuration used for estimates. Stop launching new actions when a time, token, or dollar limit is reached. Cancel and restart must preserve completed evidence.

**Acceptance:** terminate the controller during a model call, during a job, and after an artifact upload. Restart must neither repeat an unknown charge silently nor lose the best valid artifact. Test budget exhaustion and operator cancellation.

## 3. Run a small research loop

Start with approved experiment actions for supported tabular tasks. The agent can choose a model, parameters, and a bounded training-derived validation design. The controller executes known code and returns measured results. This gives the agent an actual experiment loop with a limited action space.

Use Draft, Analyze, Debug, and Improve roles or operations, with a journal of hypotheses, changes, results, and failed attempts. These operations are documented in [AIRA-dojo's solver guide](https://raw.githubusercontent.com/facebookresearch/aira-dojo/main/docs/SOLVER_DEVELOPMENT.md). Do not require separate models for every operation.

Select candidate artifacts using development results only. Keep the best valid candidate independently of the last attempt. Treat model commentary as interpretation; deterministic measurements remain authoritative.

**Acceptance:** one task completes from brief to a saved model and report; a deliberately broken last attempt cannot erase the prior model; every reported metric resolves to an executed run. The product must state that approved actions limit the search space.

## 4. Extend the isolated code runner

The first runner accepts one Python file with standard-library dependencies. It uses the dedicated AutoKaggle Civo cluster, a fixed image, gVisor, private per-run storage, network denial, and bounded output collection. Its application gate requires passing runtime and controller records plus current control checks. See [the acceptance record](../deploy/README.md) for the current result. Scientific package images, GPU execution, and a durable multi-job queue remain future work.

Use a separate non-root execution environment with fixed resource limits, read-only approved inputs, and a private working directory. Deny network traffic by default. Provide a prepared package cache when dependencies are needed. Give the worker no organizer credentials, service-account token, container socket, or shared private cache.

The controller makes model API requests outside this environment. Its tool interface accepts bounded actions and returns filtered observations; it must not become an unrestricted network proxy. Keep literature retrieval in a separate preparation stage with recorded sources. Record any later exception to that policy.

**Acceptance:** execute tests that try to read the holdout, access another run, reach public and private network addresses, read environment secrets, exceed resource limits, and modify the evaluator. Denial must be enforced and recorded. An environment variable that asks software to stay offline is insufficient. Kubernetes network controls also need a supporting implementation. [Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)

## 5. Separate prediction from scoring

The private draft API validates prediction CSV submissions and code-runner results. It keeps final scores private and stores a per-team UTC daily allowance with idempotent retries. Code execution is available only when the runner acceptance gate passes. Public team enrollment and the final release workflow still require the work below.

Freeze the selected model artifact and its environment before final evaluation. The prediction worker receives hidden input features but no answer labels. It writes a bounded prediction file. A distinct scorer validates identifiers, row count, types, finite numbers, and metric-specific values before comparing predictions with labels.

Only the trusted controller can authorize final evaluation. Maintain a persistent ledger with task, run, artifact hash, request state, and outcome. A transport retry returns the saved result; it does not grant a new query. Do not reveal label-bearing tracebacks or row-level correctness. Do not feed the final score back into another optimization cycle under the same declared run.

**Acceptance:** concurrent final requests consume one allowance; restart preserves it; modified artifacts cannot reuse the approval; invalid predictions produce safe errors. A scientist can reproduce the aggregate result privately from the frozen artifacts.

## 6. Produce a report for scientific review

Generate a draft with the question, data and exclusions, validation design, baseline, experiments, ablations, uncertainty, measured cost, failed trials, and limits. Keep a machine-readable map from tables and figures to run artifacts. Verify literature references. Separate reproduced baselines from values taken from papers.

A reviewer should test whether the evidence supports the stated claim. Improved prediction is not automatically a new scientific explanation. Research with no useful improvement should still produce an accurate negative result. Public release remains a separate human decision.

**Acceptance:** planted unsupported claims are flagged; all numeric results have evidence; no private data appear in the public report; the reviewed result can be rerun from the recorded environment.

## 7. Evaluate the whole system before scaling

Use clean tasks, public-answer fixtures, target proxies, related groups, time leakage, malformed files, and independent random-label controls. Measure valid-run completion, unsupported claims, missed leakage, false alarms, cost, and researcher effort. Repeat across seeds and retain failures.

For public-data red teaming, report attempted retrieval, successful retrieval, prohibited information use, and final performance separately. Above-chance performance alone does not identify its cause. Fresh private labels remain preferable when the aim is to measure generalization. Publish the access assumptions and checks with each benchmark result; do not describe the system as impossible to exploit.
