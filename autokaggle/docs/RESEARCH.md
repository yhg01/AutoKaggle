# AutoKaggle: research and prototype design

Research date: 26 October 2026. Audience: the Co-Scientist team.

**Build AutoKaggle around the Challenge design roadmap.** The onboarding harness should inspect data, define an evaluation, test shortcuts, and produce reproducible challenge artifacts. It must also be able to conclude that more data or a different task is needed. A train/test split alone cannot establish useful scientific progress.

**Current MVP boundary:** scope → data audit → development trial → review → two executable task packages. The researcher package contains training data. The organizer package contains the holdout and evaluation tools. The MVP does not run arbitrary research-agent code, enforce a final-evaluation query budget, or generate and publish a research paper. The proposed downstream research lifecycle in section 7 is future work, detailed in [FUTURE_BACKEND.md](FUTURE_BACKEND.md).

This report separates **documented practice** from **our proposed design**. The public evidence covers substantial parts of challenge preparation, but it does not reveal Kaggle's complete internal operating procedure. No interviews or private Kaggle materials were available. The [source register](SOURCES.md) records the evidence and its limits.

## 1. What organizers do before a challenge opens

Kaggle's hosting presentation allocates about two to three months to problem definition, scoping, and setup. It describes a supported service, so this is evidence of the work involved, not a required schedule for AutoKaggle. [Kaggle hosting presentation, page 6](https://www.kaggle.com/static/slides/meetkaggle.pdf)

The central activity is deciding what the data can support. In a first-hand interview, Kaggle data scientist Wendy Kan explains that a host's original question often does not match its dataset. Her work includes discussing the objective and finding a useful task that the available evidence can answer. Automating a questionnaire without this step would preserve the wrong question more efficiently. [Wendy Kan interview, competition-design discussion](https://www.gcppodcast.com/post/episode-84-kaggle-with-wendy-kan/)

The *Challenge design roadmap*, co-authored by Kaggle's Addison Howard and Walter Reade, provides the backbone. It includes a worked proposal, leakage guidance, and trial runs before launch. Its four pillar names structure the following proposed MVP. [Roadmap, section 1 and appendices A/C](https://data.mlr.press/assets/pdf/v02-10.pdf)

| Roadmap pillar | Proposed onboarding implementation | Target evidence |
|---|---|---|
| **Good problem** | Scientific brief, dataset audit, target and metric | A measurable claim supported by the available data |
| **Proposal review** | Critic report and scientist review | Resolved blocking questions; explicit split and access decisions |
| **Good logistics** | Resource estimate, repeatable trial, baseline, evaluator | Successful trial and saved artifacts; measure runtime and cost as execution expands |
| **Good participation** | Clear instructions, starter materials, progress, support | An independent researcher can run and understand the task |

The pillar names come from the roadmap. The implementation choices are ours. They turn each pillar into reviewable evidence without claiming that AutoKaggle duplicates Kaggle's private process.

External review also matters. NeurIPS competition selection examines the scientific question, adequate training and test data, baseline availability, evaluation validity, rules, and feature leakage. These criteria provide a useful independent check on an organizer's proposed task. [NeurIPS 2025 competition criteria](https://neurips.cc/Conferences/2025/CallForCompetitions)

**Our proposed reconstruction of the workflow:**

| Decision | Evidence to collect | Result to preserve |
|---|---|---|
| What scientific claim is being tested? | Research objective, target population, prediction time, intended use | A task statement and its limits |
| Can these observations answer it? | Data origin, measurement process, labels, missingness, available features | A data report and unresolved questions |
| What counts as progress? | Current method, cost of errors, useful improvement | Metric, baseline, success criterion |
| What would give a misleading score? | Shared subjects, future information, duplicates, public answers | Split rationale and threat report |
| Can someone complete the task? | A baseline run in the intended environment | Working example, measured runtime and cost |
| Is release justified? | Review of the evidence above | Approve, request changes, or collect more data |

Each decision should retain its evidence, author, date, and version. An agent's inference should remain distinguishable from a scientist's statement or a measured result.

## 2. The evaluation must match the scientific question

Define a prediction contract early: **one input unit, the information available at prediction time, the output, and the population or period on which it must work**. For example, “predict a patient's response before treatment at a new hospital” gives different requirements from “predict another measurement from an existing patient.”

Kapoor and Narayanan distinguish leakage from poor separation, invalid features, and a test distribution that does not support the scientific claim. A protected answer file does not address the latter two. AutoKaggle should therefore record feature availability and the intended generalization claim, not just column types. [Leakage and the reproducibility crisis in ML-based science](https://pmc.ncbi.nlm.nih.gov/articles/PMC10499856/)

Dataset documentation should record why the data were collected, what they contain, how collection occurred, and intended uses. These are questions for the data owner when files cannot answer them. [Datasheets for Datasets](https://arxiv.org/abs/1803.09010)

For this prototype, use a narrow first scope: tabular supervised classification and regression with a named target. Preserve an incomplete design when there is no dataset. Do not manufacture labels, a metric, data rights, or a claim of sufficient evidence to finish the form.

**Split policy should follow the task:**

| Data and intended use | Proposed split |
|---|---|
| Independent samples from the same population | Random rows; consider stratification for classification |
| Multiple samples from one patient, object, experiment, or source | Keep each group together |
| Prediction of later events | Hold out later observations; check feature timestamps |
| Generalization to a new site or instrument | Hold out sites or instruments where the data permit it |
| Known public labels for all records | Treat as a public-data benchmark; seek fresh private evaluation data |

Group and temporal cross-validation methods exist because ordinary random splits do not fit every dependence structure. [Scikit-learn cross-validation guide](https://scikit-learn.org/stable/modules/cross_validation.html)

An 80/20 ratio can remain a prototype default after the split unit is established. Group sizes can make the realized proportion differ. Show actual row and group counts. Keep the split stable across retries. Small tests need explicit uncertainty: the number of independent units matters more than the number of nearly identical rows. Evaluation guidance covers test size, uncertainty, and staged feedback, including patient-level separation. [How to judge a competition, section 3](https://ai-competitions-book.github.io/chapters/chapter4.pdf)

Preprocessing also belongs inside the boundary. Learn imputation, scaling, feature selection, and other fitted transformations from training data only. A pipeline can apply the resulting transformation to held-out data without fitting it again. [Scikit-learn common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html)

## 3. Concrete cases to learn from

**YouTube-8M: create evaluation evidence that is not already public.** Kan describes the need to analyze new videos and withhold labels because answers from the original release were available. This is a direct organizer account of changing the data preparation to make evaluation credible. The inference for AutoKaggle is clear: moving an existing public answer into private storage does not make it new evidence. [Wendy Kan interview, YouTube discussion](https://www.gcppodcast.com/post/episode-84-kaggle-with-wendy-kan/)

**Dog Breed Identification in MLE-bench: an agent can find the upstream source.** A 2026 issue reports that an agent independently recognized the Stanford Dogs source. The maintainers added the public-label risk to the benchmark's known issues. This is a failure case in a benchmark adaptation; it is not proof that the original Kaggle competition had the same evaluation setup. AutoKaggle should record source lineage and label publication status. [Issue 128](https://github.com/openai/mle-bench/issues/128), [maintainer known-issues list](https://github.com/openai/mle-bench)

**Multi-Modal Gesture Recognition in MLE-bench: answers can be inside a feature file.** An agent log review found that test `.mat` files contained label data, leading to a perfect result. The maintainers also list this problem. Removing a visible target column is therefore only one check. File contents, nested fields, metadata, and generated artifacts can carry answers. [Issue 77](https://github.com/openai/mle-bench/issues/77), [maintainer known-issues list](https://github.com/openai/mle-bench)

**TensorFlow Speech Recognition in MLE-bench: preparation can break the task contract.** A reported error left test labels outside the intended category mapping. This demonstrates a different risk: a bad score may come from the evaluator, not the research method. AutoKaggle needs fixtures that test the meaning of labels, as well as access restrictions. [Issue 63](https://github.com/openai/mle-bench/issues/63)

These cases support regression tests. They do not establish how often failures occur across all competitions.

## 4. Hidden tests and agent access

Kaggle's standard prediction format exposes test **features** and hides their **answers**. It uses a submission template and an answer file for scoring. AutoKaggle's proposed requirement is stronger: researchers must not see any held-out rows. That requires a submitted model or prediction program to run in a trusted evaluation environment. A CSV-only submission service normally needs to expose the inputs that participants must predict. [Kaggle competition setup documentation](https://www.kaggle.com/docs/competitions-setup)

For the first prototype, keep the participant export limited to training data and the challenge specification. Permit the organizer to inspect and download the holdout. Describe built-in baseline scoring as an organizer trial. A later research loop can use restricted, approved experiment actions before arbitrary code execution. Do not represent a local file directory as a secure server for arbitrary agent code.

**Proposed production boundaries:**

| Component | Permitted access | Excluded access |
|---|---|---|
| Onboarding service | Scientist's materials and data inspection | Research-agent execution privileges |
| Research sandbox | Approved training data, tools, writable working area | Holdout storage, organizer credentials, unrestricted network |
| Model runner | Frozen submitted artifact and hidden input features | Hidden answers, internet, organizer storage |
| Scorer | Validated predictions and hidden answers | Untrusted code execution |
| Controller | Job status and approved aggregate result | Passing private rows or errors into research context |

Use distinct identities and mounts. Run submitted code with resource limits and network access denied. Keep the model API connection in the controller; do not give the research sandbox a general proxy. Record denied access and suspicious requests. A different hostname or namespace does not by itself prove isolation: Kubernetes network policies require an enforcing network plugin, and their effect must be tested. [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)

An offline sandbox closes a retrieval route, but it cannot erase prior model training or cached data. MLE-bench studies contamination and reports results for particular model and benchmark conditions; those experiments are not a guarantee for a new model or dataset. [MLE-bench paper](https://arxiv.org/abs/2410.07095)

Repeated aggregate feedback is another route to a misleading result. The Ladder paper shows why adaptive submissions can overfit a hidden leaderboard. The current prototype uses training-derived development data. A future evaluation service should permit one final evaluation per declared run after artifact freeze. The exported local scorer does not enforce that limit. More feedback requires a distinct validation protocol and query budget. [The Ladder](https://proceedings.mlr.press/v37/blum15.html)

The release claim should be **“passed these checks under these access assumptions.”** No finite checklist establishes that a challenge is impossible to exploit.

## 5. A useful first agent workflow

The following is our design recommendation, not a claim about Kaggle's internal software.

1. **Capture a rough brief.** Ask for objective, target, data source, expected output, and why improvement matters. Accept incomplete answers and files in either order.
2. **Inspect the dataset.** Determine schema, target quality, missingness, duplicates, likely identifiers, possible groups, and candidate time columns. Record measured evidence with each finding.
3. **Ask the next important question.** Prefer a decision that changes the task or split. Show a checklist. Limit a round to one focused topic and a small number of questions. Keep unknowns visible instead of repeatedly asking for the same fact.
4. **Draft the challenge.** State metric, split policy, baseline, constraints, data rights, expected compute dollars, token dollars, and unresolved assumptions. A range or “unknown” is a valid budget answer.
5. **Run deterministic checks.** Use code for split integrity, hashes, target exclusion, schema validation, and basic baselines. An LLM may interpret findings, but its prose cannot change a failed check to a pass.
6. **Ask for review.** The scientist confirms the scientific claim and feature availability. The organizer reviews data suitability, access policy, and release risks. Freeze a version only after the required decisions are recorded.
7. **Export two packages.** The participant package contains allowed data and instructions. The organizer package contains the audit, split record, private holdout, and evaluation configuration. Make their access paths visibly different.

A short conversation should end with a reviewable draft, even when it is blocked. A missing-data task should end with a collection plan. Never reward the agent for making every checklist item green regardless of evidence.

Use structured fields for each decision: value, status, evidence, source, and reviewer. Suitable statuses include unknown, proposed, measured, confirmed, and blocked. Changing the target, source data, metric, or split should invalidate dependent approval and require new checks.

The onboarding MVP needs human review of the scientific scope, split, and permitted features before package creation. Routine measurements and repeated checks can run without a person. A future research backend needs a separate publication decision. Later automation should be earned through agreement with expert reviews on held-out onboarding cases.

## 6. Tests that define a credible prototype

| Fixture or action | Expected behavior |
|---|---|
| Vague brief with no file | Produce a draft and a short list of missing evidence; no invented results |
| Clean classification/regression data | Produce stable splits and a runnable baseline |
| Duplicate or related rows | Report risk; verify the chosen split keeps prohibited overlap out |
| Future-derived feature or a copy of the target | Flag the feature; require a decision before release |
| Public dataset with published answers | Retain a contamination warning and request private evaluation evidence |
| Bad target, missing labels, or too few independent units | Explain the problem; prevent a false ready state |
| Invalid metric/label mapping | Reject the configuration or submission; provide a safe error |
| Participant export and API | Contain no held-out rows, answers, private credentials, or organizer-only artifacts |
| Retry or process restart | Preserve data versions and split membership |
| Change a frozen scientific decision | Invalidate dependent results and approval |
| Text in a dataset says “ignore rules” | Treat it as data; do not change access or evaluation policy |

Release tests also need operational evidence: actual participant requests denied, actual network attempts blocked, and submitted code unable to read labels. Tests inside one trusted Python process do not demonstrate these boundaries.

For the planned noise-data experiment, generate features and independent Bernoulli(0.5) labels using a private generator state. Keep seed and full labels out of the participant package. Expected accuracy is 50%; a finite sample can exceed it by chance. For 1,000 independent test items, an approximate 95% reference interval is 46.9–53.1%, from `0.5 ± 1.96 × sqrt(0.25 / 1000)`. Use an exact binomial calculation for decisions, and account for the number of runs.

Compare a fresh private control with a controlled public-source variant. Measure attempted access, successful retrieval, prohibited information use, and score separately. A high score alone is not proof of misconduct; a denied request is not successful leakage. Keep this experiment separate from real researcher data.

## 7. AIRS-Bench and a future research harness

Meta's **AIRS-Bench** is a useful executable-task reference. Its repository separates task metadata, the agent's problem description, participant data preparation, evaluation data preparation, and scoring. It supports AIRA-dojo and MLGym task formats. This gives AutoKaggle a concrete output contract for an approved challenge. [Official AIRS-Bench repository](https://github.com/facebookresearch/airs-bench)

The paper evaluates research through task performance; it does not establish that a good benchmark score is a publication-ready scientific contribution. Its Appendix C is also explicit that internet access was allowed. AIRA-dojo's `HF_OFFLINE` setting could be changed by the agent. The table reports test scoring of every AIRA-dojo solution versus final-only scoring for MLGym; this alone does not establish which scores entered agent context. The paper identifies submission-format errors, lost intermediate results, and long-context failures. [AIRS-Bench, conclusion and Appendix C](https://arxiv.org/html/2602.06855v3)

A code inspection of the SICK classification task confirms the boundary: participant preparation includes test sentences with labels removed, while evaluation preparation supplies labels separately. Thus AIRS-Bench's task format must be adapted for AutoKaggle's stronger requirement to hide test inputs as well. These scripts depend on the harness to give each process the correct mounts; file names alone do not enforce access. [Participant preparation](https://raw.githubusercontent.com/facebookresearch/airs-bench/main/airsbench/tasks/rad/TextualClassificationSickAccuracy/prepare.py), [evaluation preparation](https://raw.githubusercontent.com/facebookresearch/airs-bench/main/airsbench/tasks/rad/TextualClassificationSickAccuracy/evaluate_prepare.py)

Its metadata records input columns, label, metric direction, and a referenced result. Its scorer checks prediction row count and calculates accuracy. AutoKaggle should add strict identifiers, schema, finite-value checks, immutable versions, and safe errors for its own contract. [Task metadata](https://raw.githubusercontent.com/facebookresearch/airs-bench/main/airsbench/tasks/rad/TextualClassificationSickAccuracy/metadata.yaml), [scorer](https://raw.githubusercontent.com/facebookresearch/airs-bench/main/airsbench/tasks/rad/TextualClassificationSickAccuracy/evaluate.py)

AIRA-dojo offers a useful separation between the task, interpreter, and solver. Its documented loop has preparation, action execution, final evaluation, and cleanup. Draft, Debug, Improve, and Analyze operators implement the research search, with saved solution records. [Task guide](https://raw.githubusercontent.com/facebookresearch/aira-dojo/main/docs/TASK_DEVELOPMENT.md), [solver guide](https://raw.githubusercontent.com/facebookresearch/aira-dojo/main/docs/SOLVER_DEVELOPMENT.md)

**Our proposed future lifecycle:** the current MVP implements onboarding and package preparation. The research loop, isolated model execution, final-evaluation service, report generation, and publication review below are downstream work.

| Phase | Agent action | Controller responsibility |
|---|---|---|
| Research context | Find relevant literature and propose a testable task | Save cited evidence; restrict source access after task freeze |
| Challenge design | Apply the four roadmap pillars and resolve key questions | Run data checks; retain scientist review |
| Experiment plan | Propose baseline, hypotheses, ablations, and budget | Validate permitted actions and spending limits |
| Research loop | Draft → execute → analyze → debug or improve | Use training-derived validation only; save code, logs, metrics, costs |
| Final selection | Choose one artifact from validation evidence | Freeze its hash before hidden evaluation |
| Hidden evaluation | Receive an approved aggregate outcome | Execute with hidden features; score separately with hidden labels |
| Report | Explain methods, results, failed trials, and limits | Link every result to a saved run; check references and unsupported claims |
| Publication review | Revise the proposed report | Human verifies scientific interpretation and authorizes release |

The next backend milestone should complete this flow for a small supported task, with visible state and restart recovery. Restricted experiment actions can give an agent real choices over models and parameters without arbitrary shell execution. Clearly report that limitation. Store the best valid artifact separately so a final broken attempt cannot erase it.

To add arbitrary research code later, implement the isolation boundaries in section 4, then test attempted label reads, network calls, shared-cache access, secret access, oversized output, and evaluator tampering. Use synthetic fixtures first. Stop a run when the time or dollar budget is reached. Final-test feedback must not start another optimization round.

A report generator can assemble a draft from verified artifacts. It must distinguish a literature comparison from a reproduced baseline, and a prediction improvement from a scientific discovery. The AIRS-Bench code license is CC BY-NC 4.0; this report proposes interfaces and original implementation, rather than copying its code. [Repository license](https://raw.githubusercontent.com/facebookresearch/airs-bench/main/LICENSE)

## 8. How to close the remaining knowledge gaps

The next research step should be a small case study, not a large survey. Interview two challenge designers and one scientist host. Relevant starting contacts include the roadmap's Kaggle authors and a ChaLearn organizer. No contact was made as part of this work.

Ask each to reconstruct an actual challenge from its first brief. Request redacted versions of the initial question, dataset audit, split rationale, baseline report, trial findings, and release checklist. Ask what changed, what evidence changed it, what stopped launch, and what only became apparent after release. Include one failed or abandoned proposal to avoid learning only from successful launches.

Convert each decision into a test case with an expert answer and acceptable alternatives. Reserve some cases for evaluation. Score AutoKaggle on missed critical risks, unsupported claims, useful question count, successful package execution, and agreement with the scientist's intended use. Review false alarms too: an agent that rejects every dataset is not a useful organizer.

The remaining uncertainty is specific: public sources do not show Kaggle's current internal thresholds, escalation rules, contract reviews, or complete leakage testing tools. Automated inspections cannot establish a dataset's true collection history. Domain experts must confirm those facts. The prototype should expose these limits while making the repeatable preparation work faster and easier to review.
