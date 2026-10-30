# AutoKaggle v0: a small challenge service

Research checked on 26 October 2026.

**Historical proposal:** This document records the initial v0 design. Its split ratios, daily allowance, and prediction-only scope were superseded. Use the [current project instructions](../../AGENTS.md), [selected MVP scope](../README.md#selected-mvp-scope), and [delivery plan](FUTURE_BACKEND.md#selected-mvp-delivery-order) for current requirements.

**Build a prediction competition with a controlled scoring API.** An agent prepares the problem and its materials. Server code enforces access, submission limits, and scoring. This provides useful Kaggle-style controls; it cannot make public answers secret or prove that a solution used an allowed method.

## What the evidence supports

Kaggle’s standard prediction format exposes test **inputs** and keeps the answer file private. A public test subset supplies feedback during the competition. A separate private subset determines final ranking. These are two divisions: training versus test, then public versus private scoring within the test set. [Official setup guide](https://www.kaggle.com/docs/competitions-setup)

Concrete controls vary by competition. RSNA 2024 allowed two entries per day and two selected final entries. Its rules require one account per person, prohibit private sharing outside teams, restrict team mergers by cumulative submission count, and require reproducible winning code. These are documented examples, not universal Kaggle settings. [Official RSNA rules](https://www.kaggle.com/competitions/rsna-2024-lumbar-spine-degenerative-classification/rules)

Repeated scores can overfit an unseen holdout. Submission limits reduce opportunities; they do not establish statistical validity. The Ladder paper studies this problem and proposes a stronger feedback method. [Blum and Hardt, ICML 2015](https://proceedings.mlr.press/v37/blum15.html)

Private storage also cannot repair published labels. Kaggle designer Wendy Kan describes obtaining new YouTube-8M videos and withholding their labels for evaluation. [First-hand organizer interview](https://www.gcppodcast.com/post/episode-84-kaggle-with-wendy-kan/)

## Minimum scope and responsibility

The following are **our v0 design choices**, informed by that evidence.

| Control | Agent or organizer decision | Server enforcement |
|---|---|---|
| Valid task | Define prediction unit, allowed inputs, target, metric, source, rights, and useful result. | Reject invalid schemas; run leakage checks and a training-only baseline. |
| Appropriate split | Choose random, group, or time split. Review repeated systems and future-derived features. | Save fixed split membership; keep labels and public/private membership out of downloads. |
| Limited feedback | Default to 80% training; split the remaining test rows 30% public and 70% private. Review adequacy before release. | Return only public aggregate scores while open; release selected private results after close. Ratios are configurable design choices, not guarantees. |
| Participant identity | Organizer issues one token per invited participant. | Scope tokens to a challenge; hash stored tokens; enforce quotas per identity. This depends on organizer identity checks. |
| Submission contract | State exact ID, prediction, metric, and class meaning. | Reject missing, duplicate, or unknown IDs, wrong columns, non-finite values, and invalid probability ranges. Return safe errors. |
| Query budget | Start with two attempts per day and one selected final entry. | Count new authenticated attempts, including invalid files. Bind retry keys to request hashes; a retry must not consume another attempt. Lock selection at close. |
| Stable challenge | Review materials before publication. | Freeze source hash, split, metric, instructions, and version. Changes require a new challenge version. |
| Review trail | Review suspicious results and require code before claiming a verified winner. | Record participant, time, file hash, version, validation result, score, and final selection. |

## Three outputs from one intake

1. **Website:** explanation, data provenance, rules, download, submission form, and public leaderboard. Include organizer controls for participant invitations and closing the challenge.
2. **API:** authenticated CSV submission, validation result, public score, submission history, final selection, and leaderboard. Publish concrete request examples.
3. **Research ZIP:** `train.csv`, test inputs without labels, submission template, task specification, dependency list, baseline, local validation command, submission client, and agent instructions. One documented command must produce a valid submission. Never include credentials, private answers, or scoring membership.

For SPOCK 2.0, label the demonstration as a public-data benchmark. The authors released a cleaned dataset after finding duplicated integrations and incorrect stability labels. Audit the local derivative and document its origin. A local holdout of published records does not support a claim of secret answers. [SPOCK 2.0 paper](https://arxiv.org/abs/2501.15017)

Full hidden-input evaluation requires a later model-submission runner with isolated storage, denied network access, resource limits, and controlled outputs. Kaggle’s hidden-test code mode reruns notebooks on replacement data and limits error detail to reduce probing. CSV submission alone cannot enforce how an external research agent works. [Official debugging guide](https://www.kaggle.com/code-competition-debugging)
