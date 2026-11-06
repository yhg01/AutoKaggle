# BOLD AutoKaggle

An agent-led interview that turns a research idea into a draft competition. The agent asks focused questions, records the agreed scope, and prepares a challenge README, website draft, research ZIP, and private prediction-submission workflow.

[Open the hosted BOLD preview](https://ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/) · [User guide](autokaggle/README.md) · [Challenge design guide](autokaggle/docs/README.md) · [API](autokaggle/docs/API.md) · [Session and data controls](autokaggle/docs/WORKSPACE.md)

## Start locally

Use Python 3.11 or later. Run these commands from the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r autokaggle/requirements.txt
cp .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env`, then start the app:

```sh
.venv/bin/python -m autokaggle.run --env-file .env
```

Open [localhost:8877](http://127.0.0.1:8877/). The server binds to localhost. The default configuration uses GPT-6.1 Sol through OpenRouter, with medium reasoning for conversation and high reasoning for draft suggestions. Without a key, the app shows a limited rules mode.

Keep `.env` private. Model calls send interview content to the configured provider. Email sign-in requires a separate sending configuration; see [email setup](autokaggle/docs/EMAIL_SETUP.md).

## Current workflow

1. Accept the data-storage notice. Describe the research problem, or use Sessions → Start from research to import a paper and public GitHub repository, edit the starting brief, and approve it. The agent asks one focused follow-up at a time.
2. Inspect the checklist under Problem, Method & deployment, Baseline, and Setup.
3. Open a checklist card to accept its scope, delegate a supported implementation choice, or record an exception. After two unsuccessful questions about one requirement, the agent offers a decision checkpoint.
4. Upload a supported CSV through Data & checks. Review the target, metric, split, permissions, and data checks.
5. Build and inspect the draft website, research ZIP, schemas, environment record, and development scoring results. Request changes to revise the challenge with its prior context.

Use Sessions to resume or delete a session, share a single-use handoff code, review attempts, or change data-storage settings. Researcher turns have an Edit or remove answer action. Compute estimates accept hardware-time, tokens, dollars, or another concrete notation. See the [session guide](autokaggle/docs/WORKSPACE.md).

The hosted service uses email codes and private account workspaces. New challenges use the signed-in address as the private organizer contact.

After email verification, a researcher with no saved name is asked for a name once. **Sessions → Profile** lets them edit it later. Session lists, shared-session members, and new message labels show names. Internal review can search all projects by researcher name and can label an existing verified account through **Project details → Researcher name**. Names are account labels; email verification and the existing account ID determine access.

## Delivered scope and limits

- CSV classification and regression workflows support data checks, draft packages, and prediction submissions. CSV uploads are limited to 200 MB, with additional row, column, and cell bounds.
- Dataset links are recorded for review. Automatic Google Drive import is not implemented in this app.
- Researchers can attach papers, notes, and logs in the chat, and can ask the agent to read a document or link, check the dataset, or search the web. A lookup runs only on request, and a finding is recorded only after the researcher confirms it. Documents give context and do not enter the package. See [looking things up](autokaggle/docs/WORKSPACE.md#ask-the-agent-to-look-something-up).
- The runtime uses an 80/20 outer split and training-derived development data. It keeps final answers private and withholds final scores. The requested 70/30 policy and public/private leaderboard workflow remain planned work.
- A scientific reference baseline is optional. The current pipeline trial uses a simple predictor; it does not reproduce an external scientific baseline.
- Hosted code execution is disabled. Operator-controlled Civo execution requires private configuration, verification receipts, and fresh runtime checks. Those receipts are not distributed in this repository.
- Scope acceptance resolves interview decisions. Data, scorer, access, and execution checks still apply. Public competition launch remains a separate step.

See the [implementation guide](autokaggle/README.md) and [future backend plan](autokaggle/docs/FUTURE_BACKEND.md) for details.

## Validation

```sh
.venv/bin/python -m pytest autokaggle/tests -q
node --test autokaggle/tests/*.cjs
.venv/bin/python -m autokaggle.scripts.live_scope_verify
```

The live check reads the private `OPENROUTER_API_KEY` from `.env`, makes real model calls, and uses an isolated synthetic project. It writes ignored test output. See [validation notes](autokaggle/docs/VALIDATION.md).

## Deployment

The deployment scripts target the existing BOLD AutoKaggle Civo installation. Review [the web deployment guide](autokaggle/deploy/WEB.md) and [runner requirements](autokaggle/deploy/README.md) before use. They require operator credentials and are not a generic cluster installer.

This repository contains application source and setup documentation. Uploaded datasets, conversations, private answers, credentials, and local deployment receipts are excluded.
