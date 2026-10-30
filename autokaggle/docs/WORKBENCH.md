# Data workbench

Start with the [short challenge design README](README.md).

A standalone local workbench for turning a research question and a CSV into a reviewed machine-learning challenge. It uses the [Challenge design roadmap](https://data.mlr.press/assets/pdf/v02-10.pdf) as its design basis and an original task-package contract informed by [AIRS-Bench](https://github.com/facebookresearch/airs-bench).

Read [the research brief](RESEARCH.md), [source register](SOURCES.md), and [future backend plan](FUTURE_BACKEND.md).

## Start

Use Python 3.11 or later. From the repository root:

```sh
python3 -m venv autokaggle/.venv
autokaggle/.venv/bin/pip install -r autokaggle/requirements.txt
autokaggle/.venv/bin/python -m autokaggle.run
```

Open <http://127.0.0.1:8877/workbench>. The server binds to this machine only.

To use the model, set `OPENAI_API_KEY` in the server environment or load a private file:

```sh
autokaggle/.venv/bin/python -m autokaggle.run --env-file /absolute/path/to/private.env
```

The default model is `gpt-6.1-sol`, with medium reasoning for scoping and high reasoning for review. Set `AUTOKAGGLE_MODEL` to use another available model. Advice uses the Responses API, with no tools or web access. Only the brief, entered decisions, schema statistics, and audit findings go to the model. Raw CSV rows do not.

Without a key, the interface shows rules mode. Data checks, baselines, packages, and preview still work. A failed model call is visible and produces rules-based advice. Each project permits at most 12 model requests, including failed or uncertain requests. Each request has a 6,000 output-token ceiling and a 120-second timeout. This is a call limit, not a dollar guarantee.

## Try the full workflow

1. Select **Materials discovery**, or create a challenge and upload a CSV.
2. Select **Run onboarding agent**. It reads the brief, records supported missing decisions, checks the dataset, runs a development trial, and writes a review. Progress and results are saved.
3. Review the objective, prediction unit, useful result, data source, permission, and cost estimates. For a new CSV, confirm the proposed target and evaluation design.
4. Resolve blockers. Select **Run checks & baseline** after any edit. Use a group split for related observations or a chronological split for future observations.
5. Review the warnings and confirm the review checkbox. Select **Prepare challenge packages**.
6. Download the training package and the private organizer package. Open the participant preview to inspect what a research agent can receive.

The **misleading shortcut** example contains a copy of the answer in `post_test_result`. The audit blocks it. Exclude that column and run the audit again.

The **random-label control** example has no predictive signal by construction. Chance performance is expected, with sampling variation. The audit does not infer impossibility from a single failed baseline.

Examples create separate drafts. The organizer session is stored in an HttpOnly cookie; clearing it removes access through that browser. Data remain in the local private store. Keep this prototype on localhost: it does not provide account login or organizer-session recovery.

## What it does

- Scientific brief and visible checklist, with a bounded model-assisted workflow.
- Strict UTF-8 CSV parsing: up to 200 MB (209,715,200 bytes), 1,000,000 rows, 200 columns, and 10 million cells. For larger files, paste a Google Drive link in the interview. Set access to **Anyone with the link** and the role to **Viewer**. The app saves the link for review; it does not import the file automatically.
- Classification: accuracy, balanced accuracy, binary ROC AUC with labels 0/1. Regression: MAE or RMSE.
- Repeatable 80/20 random, group, or chronological partitions. Random classification splits use stratification. Groups and equal timestamps stay together, so their ratio can differ from 80/20.
- Checks for missing/invalid labels, target copies, possible proxies, repeated source identifiers, duplicate features across the split, and inadequate partition sizes.
- A bounded tree and constant-reference baseline, evaluated on a development split **inside training**. Final test rows are never used for baseline fitting or scoring.
- Review approval and separate researcher/organizer ZIP files with SHA256 manifests.
- Participant capability links that expose only the training package. Any change revokes the old link and requires a fresh audit and package.
- Saved run events, source evidence for accepted model updates, model token counts, and recovery notice after an interrupted run.

## Package contract

| Researcher ZIP | Private organizer ZIP |
|---|---|
| `train.csv` | `test.csv` with labels |
| `project_description.md` | `project_description.md` |
| `metadata.yaml`, `task.json` | `metadata.yaml`, `task.json` |
| `prepare.py` | `evaluate_prepare.py`, `evaluate.py` |
| `requirements.txt`, `manifest.json` | `audit.json`, `trace.json`, `requirements.txt`, `manifest.json` |

`metadata.yaml` uses JSON syntax, which is valid YAML. No fabricated SOTA reference is supplied. This contract is inspired by AIRS-Bench; direct integration with AIRA-dojo or MLGym has not been validated.

`prepare.py` copies the approved training data. The private `evaluate_prepare.py` creates separate feature and truth directories, preserving source cell text. It refuses overlapping or unsafe inference directories. The scorer accepts only strict CSV predictions and never executes submitted code. It validates row identifiers, schema, finite values, and metric requirements.

The web app deliberately exposes no participant scoring endpoint. Its scope ends with a reviewed, executable task package. The actual research loop and final evaluation require a separate trusted controller and isolated prediction runner. The [backend plan](FUTURE_BACKEND.md) specifies those steps and their acceptance tests. The reference scorer alone does not enforce a one-submission policy.

## Storage and configuration

Runtime files are under `autokaggle/data/`, excluded from Git. The store uses SQLite and per-project directories. Set `AUTOKAGGLE_DATA_DIR` for a different private location. Use one server process. Concurrent writes to a project are rejected while an action runs; other projects remain available. A maximum of two background onboarding jobs run at once.

Supported configuration:

| Setting | Default |
|---|---|
| `OPENAI_API_KEY` | Unset; rules mode |
| `AUTOKAGGLE_MODEL` | `gpt-6.1-sol` |
| `AUTOKAGGLE_MODE` | `model`; use `rules` to disable model calls |
| `AUTOKAGGLE_DATA_DIR` | `autokaggle/data` |
| `--port` | `8877` |

An access-controlled production service, durable distributed jobs, large-file/Drive ingestion, and arbitrary research code execution are future work. Do not expose this local application to the public internet. A passed audit does not establish data provenance, scientific validity, or absence of all leakage.

## Tests

From the repository root:

```sh
autokaggle/.venv/bin/python -m pytest autokaggle/tests -q
```

Tests cover data validity, split stability, group/time separation, target leakage, API ownership, participant exports, edit invalidation, actual exported scripts, malformed predictions, model errors, and limits. See [VALIDATION.md](VALIDATION.md) for the actual browser and integration checks performed during this build.
