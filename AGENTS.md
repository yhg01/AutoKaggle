# Project instructions

## Follow the Kaggle workflow

For all work in this project, reproduce the Kaggle competition workflow as closely as the task permits. Use official Kaggle documentation and published competition rules as the first reference. Explain any necessary difference and record it in the affected documentation. Do not assume that Kaggle's private security infrastructure is publicly documented.

These decisions were approved by the project owner on 27 October 2026:

- Support prediction competitions and code competitions. Ask the organizer to choose a type in the onboarding checklist. Prediction submissions use visible test inputs and private answers. Code submissions run privately against hidden inputs; keep answers outside the submitted program.
- Use the **AutoKaggle** Civo Kubernetes cluster in **lon1**, ID `ecc962fa-2f4c-4a3f-96c4-179af273fb7a`, for research code execution. Keep untrusted execution separate from trusted scoring and credentials. Disable code execution until sandbox and access tests pass. Do not describe a system as impossible to compromise.
- Default to **five submissions per team per UTC day**. Ask the organizer to confirm or change this limit. Enforce the limit on the server. Retries must not create duplicate submissions. Failed execution counts toward the allowance.
- For prediction tasks with an existing labeled dataset, keep a 70/30 training/test split by default. Use training-derived validation for local development. Divide the held-out test pool into public and private leaderboard subsets under the policy below. Keep all test answers private and withhold private scores during development. State the exact data access policy for the selected competition type.
- Onboarding must produce the challenge README, website draft, research ZIP, input/output contract, data and artifact versions, dependency/environment specification, metric version, resource limits, and compute/token budget record. Mark missing information explicitly. Never describe a template as a completed execution test.
- Test the submission and scoring process with a simple valid attempt. Keep scorer checks mandatory. A scientific reference baseline is optional, including for novel problems without a functional reference. Return measured results, failures, and open decisions to the organizer before publication.
- Collect and validate a private organizer email before the scientific interview. Once the complete draft workflow is ready, send a private login link and links to the website, research ZIP, and submission test. Use `boldcoscientist@gmail.com` as the configured sender. Keep email credentials, login tokens, organizer addresses, and test answers out of participant packages and logs.
- Keep creation, review, and publication separate. Public launch is deferred. An organizer must be able to review the first version without publishing it.

## Agent-led onboarding interview

Use an interview as the main interface. The agent asks the questions. Show four sections in order: **Problem**, **Method & deployment**, **Baseline**, and **Setup**. Put organizer settings in the fourth section. Use the detailed checklist to guide the agent; do not require the researcher to complete a webform.

- Use this readiness definition: **Within the agreed scope, another research agent can implement an attempt and interpret its score without inventing scientific assumptions.** All applicable decisions outside the optional reference baseline are compulsory. Record evidence for each required detail. A general answer or an item marked answered is not sufficient by itself.
- Keep a checklist visible during the conversation. Show the number of required details recorded for each item and topic, with the evidence and remaining gaps. These bars measure definition coverage, not scientific accuracy. Unknown and deferred required details remain blockers. A documented, explicit reason can establish that a conditional requirement does not apply. Keep application execution checks separate from researcher progress.
- The organizer can manually bypass an interview requirement from its checklist details. Require a written reason and keep the source facts. Mark the requirement **Manually bypassed** and count it as resolved for interview progress. This is a user-approved exception to the compulsory definition rule. It does not establish missing scientific facts. Carry the reason into the challenge README, participant instructions, challenge record, and organizer review. Preserve the change history. Allow the organizer to remove the bypass. Adding, changing, or removing a bypass requires a rebuilt package before a new review invitation. Validated email, competition type, submission allowance, and application data, scorer, submission, runner, and access checks cannot be bypassed; they are needed to operate the service. The optional baseline needs no bypass.
- Allow a working draft with open questions. Do not label it ready to build or ready for review until all required definition details are resolved. A question limit is a checkpoint, not evidence of readiness. At the limit, summarize the remaining gaps and allow another bounded interview round. A complete technical dataset check cannot override missing scientific decisions.

- Preserve accepted requirements when the researcher adds compatible information. An omitted model assessment or an unknown answer to one follow-up must not erase unrelated progress. Reopen only requirements affected by a correction or an evidenced contradiction. Reassess saved facts before asking the researcher to repeat them.
- Each follow-up must identify one unresolved requirement and explain its practical effect on the attempt or score. After two unsuccessful questions about that requirement, stop automatic clarification and offer scope resolution. A new interview round must not reset this limit for an unchanged gap.
- Let the organizer select **Accept this scope** in a scientific card. Show one editable summary and list which remaining decisions it confirms. Keep confirmed definitions, bounded delegated implementation choices, and accepted scientific exceptions distinct. Delegation is limited to supported implementation choices within platform and data access limits. Exceptions retain their unresolved assumptions. Store decisions and change history; include them in the README, participant instructions, challenge record, and review. Scope changes require rebuilt artifacts. Validated organizer settings and technical execution checks remain mandatory.

- Read the complete brief and each reply. Record all supported facts before choosing the next question. Ask one relevant question about a missing scientific decision. Do not repeat information already supplied, deferred, or marked unknown.
- Ask for dataset source links. Also offer CSV upload for files up to 200 MB through **Data & checks** at the bottom left. Use a shared link for larger files. The standard is a Google Drive file or folder shared as **Anyone with the link**, with the **Viewer** role. Accept direct dataset URLs and repository links. For generated data, ask for the generation setup and its code or documentation link if available. Reuse supplied links and do not repeat requests marked unknown or unavailable. Record a link as a source reference; it does not establish access, permission, inspection, or import. The current AutoKaggle app records links but does not download them.
- Keep recorded facts, unresolved gaps, and agent suggestions distinct. Accept corrections and preserve facts that the correction does not change. A researcher can request a draft with open questions.
- Separate the scientific objective, method, submitted artifact, and deployment setting. A neural network is a method; a prediction file is an artifact. Record what the deployed solution can observe, when it acts, and which resource limits apply.
- Define how the artifact produces the measured outcome. For trading, distinguish forecast accuracy, a historical backtest, and later market performance. Record the policy that converts forecasts into positions, costs, execution assumptions, and risk limits when these affect the objective.
- Ask for the strongest relevant reference method known to the researcher when useful. Record its source, code or weights, reported score, data, and execution conditions where available. This is the only optional interview topic. An unknown, unavailable, or absent reference must not prevent readiness. Do not invent a state-of-the-art result or repeat a declined baseline request.
- Keep published or researcher-reported baseline scores separate from measured reproduction results. If reference reproduction is attempted, record what the application ran through the submission and scoring process. The interview must not ask the researcher to certify an application run or imply that reproduction occurred. A constant predictor tests the pipeline; it does not reproduce a scientific reference method.
- Use baseline failures to identify missing task details, data, code, dependencies, compute, or deployment assumptions. Required scientific gaps still block readiness. Lack of a functional reference alone does not block a novel challenge. Record causes and differences without treating an optional reproduction as a mandatory gate.
- Collect validated competition type and daily allowance through conversation when needed. Explain the choice before asking. Only the private correspondence email is required before the interview.
- Provide a separate organizer review chat. Start by asking: "What do you want to see changed? Is the issue in the problem definition, method and deployment, or our attempt to reproduce the baseline?" Let the organizer direct the changes. Keep previous messages, facts, draft context, and measured trial results. Ask targeted follow-ups about the requested changes. Keep each revision bounded, and preserve unrelated facts. Rebuild artifacts after a change before sending a new review invitation.
- Keep progress summaries concise. Place draft review, package preparation, data checks, and measured trial results in secondary views. Preserve access to these functions without making the interview a long page of controls.

## Selected MVP scope

The project owner selected types **1, 2, 3, 5, and 7** from the Kaggle competition survey on 29 October 2026:

| Survey type | Required workflow |
| --- | --- |
| 1. Classic prediction | Accept a prediction file and score it against private answers. |
| 2. Code with hidden inputs | Execute a frozen code artifact on hidden inputs in the isolated Civo runner, then score its output separately. |
| 3. Code with an inference API | Give the submitted program only the current approved input or batch. Collect a bounded response before advancing. |
| 5. Live forecasting / future data | Freeze submissions before the final data become available. Collect and version the later data, then evaluate the frozen entries. |
| 7. Optimization | Validate a candidate solution against explicit constraints and calculate a deterministic objective. |

- Keep submission format, evaluator type, and holdout policy separate. These five workflows overlap. Future-data evaluation can use the code or inference API path.
- Reuse the challenge record, research package, versioned evaluator, submission ledger, daily allowance, final-entry selection, and organizer review. Keep the compact chat interface. Ask only the follow-up questions required by the selected workflow.
- For an inference API, the first version should use a local protocol controlled by the runner. Participant code must not gain unrestricted network access or access to later inputs through mounted files.
- For live forecasting, require a data source, submission cutoff, collection window, outcome availability rule, and correction policy. Late or incomplete data must have a recorded status. A historical replay can test the mechanism, but cannot establish that a live future-data cycle occurred.
- For optimization, require an input schema, candidate schema, feasibility checks, objective direction, numeric tolerances, and resource limits. A labeled training set or `solution.csv` is optional. Private instances are needed only when the task must measure generalization beyond the published instances.
- Other survey types are outside the current MVP. The selected scope is a development requirement, not a claim that every workflow is already implemented. Follow the delivered status and build order in `autokaggle/README.md` and `autokaggle/docs/FUTURE_BACKEND.md`.

## Public and private leaderboard policy

Added at the project owner's request on 29 October 2026. Follow Kaggle's [setup guide](https://www.kaggle.com/docs/competitions-setup) and [competition rules](https://www.kaggle.com/competitions/the-new-era-of-competition/rules).

The row-based policy below applies to prediction tasks with a fixed labeled test pool. Future-data tasks need a time-based holdout. Optimization tasks need a declared instance and objective policy; they do not require artificial target labels.

- Treat the training/test ratio and the public/private leaderboard ratio as separate decisions. Ask the organizer to confirm both. Keep related samples together where the scientific design requires this. Freeze the assignments for a challenge version.
- Keep the answer key in a private `solution.csv` or equivalent scorer store. It maps each test ID to its answer and `Usage` value: `Public`, `Private`, or `Ignored`. Neither the answers nor this mapping can enter participant files or submitted code.
- Prediction competitions must accept predictions for the complete test input file. Return only the aggregate public-subset score during the competition. Keep public/private membership hidden: file names, IDs, row order, metadata, and published split seeds must not disclose it. Use the same fixed subsets across submissions and teams.
- Before the deadline, teams select saved, eligible submissions for final ranking. Record the allowed number, fallback selection rule, deadline, and scoring-completion rule in onboarding and the challenge README. Freeze the selected artifacts before private scores become available. Do not let teams choose or modify entries after seeing private results.
- Final ranking uses the private-subset scores of those selected entries. A standard prediction competition reuses the stored predictions; it does not require a new upload after the deadline. For code competitions, freeze code, dependencies, and model assets; the evaluator can run that fixed version on hidden inputs. Answers and membership stay in the trusted scorer.
- Keep the five-per-day default, bounded score precision, and safe error responses. These controls reduce adaptation to leaderboard feedback. They do not prevent all overfitting or disclosure of answers already available elsewhere.
- Keep the intended policy separate from delivered behavior. The current prototype uses an 80/20 outer split and separate development/final input files. It scores development submissions only. The 70/30 policy, hidden leaderboard membership, final-entry selection, and leaderboard release still require implementation.

## Primary references

- [Competition setup](https://www.kaggle.com/docs/competitions-setup)
- [Competition formats and participation](https://www.kaggle.com/docs/competitions)
- [Private code execution and safe errors](https://www.kaggle.com/code-competition-debugging)
- [Notebook environments and versions](https://www.kaggle.com/docs/notebooks)
- [Hosting services](https://www.kaggle.com/c/about/host/)
- [Competition creation API](https://github.com/Kaggle/kaggle-cli/blob/main/docs/competition_creation.md)

Use short, direct sentences. Preserve existing work. Report what was actually tested and identify dependencies that still prevent a complete run.

## Branch and commit naming

Use descriptive branch names without AI product or model names. Keep those names out of commit messages as well. Do not add attribution signatures, generated-by footers, or co-author trailers. Do not commit or push changes until explicitly requested.

## Live API testing

Added at the project owner's request on 29 October 2026.

- For all test work, use live API calls through OpenRouter to test the system with real model responses. Load `OPENROUTER_API_KEY` from the private `.env` file in the project root.
- Each test run must include live validation of the affected model workflow. Unit tests and test substitutes can support this check, but they cannot replace it.
- Select and record an OpenRouter model that supports the tested interface. Saving this key does not change the application's existing model provider. Configure the test path to use OpenRouter before claiming live OpenRouter coverage.
- If the key, model, or service is unavailable, report the blocked live check. Do not silently substitute another provider or describe simulated responses as live evidence.
- Record the model, tested behavior, result, and any external limits. Keep test inputs small and relevant.
- Keep the API key in the private environment file. Never copy it into source code, documentation, logs, screenshots, or committed files. Keep `.env` excluded from Git.
