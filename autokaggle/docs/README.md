# Challenge design interview guide

The agent uses this guide to interview the researcher. It is adapted from [Challenge design roadmap](https://data.mlr.press/assets/pdf/v02-10.pdf), Sections 1–2 and Appendix C, and the project owner's scientific requirements. The researcher supplies domain facts. The agent records them, identifies missing decisions, and asks one useful question at a time.

Read the entire brief and each reply before asking a follow-up. Reuse facts already supplied. Accept unknowns, deferred decisions, and corrections. Keep suggestions separate from confirmed answers. A draft can contain open questions.

**Within the agreed scope, another research agent can implement an attempt and interpret its score without inventing scientific assumptions.** All applicable requirements in Problem, Method and deployment, and organizer settings are compulsory. The scientific reference baseline is optional. Use explicit requirement records and supporting evidence. A broad answer does not complete every requirement in its topic.

Unknowns remain recorded gaps. They do not count as complete. Conditional requirements need an explicit reason when they do not apply. A working draft remains available, but unresolved required details block readiness and review invitations. Eight follow-up questions end a round, with a gap summary and the option to continue. They do not establish that the challenge is complete.

The organizer can bypass a requirement from its checklist details with a written reason. This user-approved exception resolves that interview requirement while retaining its source facts and remaining scientific uncertainty. Show **Manually bypassed**, keep the change history, and carry its reason into the README, participant instructions, challenge record, and review. The agent must not invent missing facts or claim that the bypass verified them. A bypass can be changed or removed; rebuild artifacts after the change. Validated email, competition type, submission allowance, and application data, scorer, submission, runner, and access checks remain mandatory. The optional baseline needs no bypass.

Current MVP scope: classic prediction, code with hidden inputs, code with an inference API, live forecasting/future-data evaluation, and optimization. These correspond to survey types 1, 2, 3, 5, and 7. Apply only the questions needed for the chosen workflow. See [scope and delivered status](../README.md#selected-mvp-scope).

## 1. Problem

Establish the scientific question before asking for platform settings.

- **Question and value:** What should improve, why does it matter, and what would count as useful progress?
- **Task:** What inputs are available and what must a solution produce? Identify the population, situation, or time period where it must work.
- **Data or environment:** Ask for a link to the available dataset, labels, problem instances, or simulator. Also offer CSV upload for files up to 200 MB through **Data & checks** at the bottom left. Use a shared link for larger files. The standard is a Google Drive file or folder shared as **Anyone with the link**, with the **Viewer** role. Accept direct dataset URLs and repository links. For generated data, ask for the setup and a code or documentation link if available. Record sources, permissions, quality limits, and known bias.
- **Evaluation:** How will the outcome be measured? Record the metric or objective, useful threshold, and conditions the test must represent.
- **Leakage:** Ask about related samples, time order, answer proxies, and public answers. The application must perform available data checks; a researcher statement alone does not establish that leakage is absent.

For fixed labeled data, confirm the training/test split and the public/private leaderboard split separately. For future data, establish the submission cutoff, collection window, outcome availability, and correction policy. For optimization, establish feasibility checks, objective direction, numeric tolerances, and instance coverage. Follow the [leaderboard policy](../README.md#public-and-private-leaderboards).

Datasets can be large. Ask for links instead of full dataset uploads or pasted rows. Reuse supplied links and do not repeat requests marked unknown or unavailable. A link identifies a source; it does not prove access, permission, inspection, or import. The current AutoKaggle app records links but does not download their contents. This rule also applies when a revision introduces replacement data.

## 2. Method and deployment

Keep these decisions distinct. A neural network is a method. Predictions, code, weights, or a candidate solution are submitted artifacts.

- **Methodology:** Can the agent choose a method freely? Which methods are required, prohibited, or the intended starting point?
- **Submitted artifact:** What must participants return? Ask for an example if the output is unclear.
- **Deployment:** Where does the solution run? What can it observe at each decision? Record latency, memory, hardware, state, update, and network limits where they matter.
- **Evaluation procedure:** How does the submitted artifact produce the outcome being scored? Record any conversion from predictions into actions.
- **Scientific restrictions:** What external data, pretrained models, or other resources are allowed? What makes a result invalid?
- **Budget and ownership:** Record a credible attempt's compute and model-token costs in dollars, including experiments and evaluation. Distinguish estimates from hard limits. Record owners and relevant dates.

For a trading task, distinguish forecast accuracy, historical backtesting, and later market performance. If forecasts become positions through a fixed policy, define that policy, transaction costs, execution assumptions, and risk limits. If participants submit a trading policy, identify the information it may use when making each decision.

Collect and validate the private organizer email before the scientific interview. Explain other platform choices when they become relevant. Collect prediction or code format and daily allowance through validated chat replies. Confirm five submissions per team per UTC day or a different allowance. Selected future workflows remain requirements until their evaluator is implemented.

## 3. Optional reference baseline

Record the strongest relevant method known to the researcher and what is required to use it in this challenge. A novel problem can have no functional reference. This does not block readiness. Do not repeatedly ask for a reference that is unknown or unavailable.

- **Reference method:** Record the paper, code, weights, version, and license or access limits where available. An unknown reference remains an optional research question.
- **Reported result:** Record the published or researcher-reported score, dataset, split, metric, and execution conditions. Identify its source.
- **Reproduction requirements:** Record preprocessing, dependencies, data access, hardware, runtime, and expected costs. Identify differences from the proposed deployment setting.
- **Useful improvement:** If a baseline exists, record what gain would matter scientifically. A useful success criterion remains compulsory even when no baseline exists; it can use an absolute target or a stated operational benefit.

The application owns any reference reproduction trial. If it runs a reference method through the declared submission and scoring process, record the measured result, failures, and differences. Do not ask the researcher to certify an application run. Do not copy a reported score into the measured-result field.

A failed reference trial needs a recorded cause. Required task details that it exposes must be resolved. Missing reference code or a reference that cannot be reproduced does not by itself block a novel challenge. The current prototype uses a constant predictor to test the submission pipeline and perfect predictions to test the scorer. These tests remain mandatory. They do not research or reproduce arbitrary state-of-the-art methods.

## Preparation and review

These are workflow duties and later decisions. They must not become a fixed sequence of extra interview questions.

- Prepare the input/output contract, valid example, data and artifact versions, dependencies, metric version, resource limits, and compute/token budget record.
- Produce the challenge README, website draft, and research ZIP. Keep missing values explicit and private answers out of participant files.
- Run the required data, submission pipeline, and scoring checks. Keep optional reference reproduction separate. Keep planned work separate from measured results. Do not count application-owned trial work as a missing researcher answer.
- Ask for an independent reviewer, participant guidance, support needs, and remaining rules when these affect the challenge. Ask only for information not already supplied.
- Present the first measured development results, failures, and unresolved decisions to the organizer. Send a private review link when the complete draft is ready. Publication is a later decision.

The interface shows four sections: Problem, Method & deployment, Baseline, and Setup. Setup is section 4 and contains the organizer settings. The internal checklist retains the existing records and adds methodology and deployment, for 17 items. It guides extraction and follow-ups; it is not a form the researcher must complete.

**Draft status:** Pending organizer review. Recorded answers alone do not establish that execution, reproduction, independent review, or publication occurred. Follow the project [Kaggle workflow instructions](../../AGENTS.md).

## Confirm the intended scope

The organizer can accept an editable card summary. Each remaining requirement must have an explicit resolution: confirmed by that summary, delegated within the supported implementation limits, or accepted as an unresolved exception. An exception does not establish a scientific fact. Delegated work must remain within the fixed data access and execution rules. Store these decisions separately from model assessments and preserve their change history. Include them in participant and organizer artifacts.

An added compatible fact keeps earlier completion. Reopen only affected requirements when evidence changes or conflicts. Before asking for more detail, assess the saved conversation and explain how the missing choice affects implementation or scoring. After two unsuccessful questions about one requirement, stop automatic questioning and offer scope resolution. Technical validation remains mandatory.
