# AutoKaggle prototype plan

Date: 26 October 2026

Build a standalone organizer workbench based on *Challenge design roadmap*:
https://data.mlr.press/assets/pdf/v02-10.pdf

1. Research the published organizer process. Record sources, decisions, evidence gaps, and practical acceptance checks in RESEARCH.md.
2. Build a local web application for a scientific brief, bounded agent advice, CSV data audit, split design, baseline trial, review, and export.
3. Keep all held-out rows private. Export a researcher package with training data and an organizer package with test data and a reference scorer. Do not execute user code.
4. Test valid and flawed cases, inspect the interface on desktop and mobile, and fix defects before delivery.

## MVP decisions

- Separate application and storage. Do not change the live intake application.
- Local organizer session with an HttpOnly cookie; participant preview has a separate capability and only approved training artifacts.
- Real CSV profiling and checks; no invented audit results.
- Random, group, and chronological split choices. Default ratio: 80% training, 20% hidden test. Group splits may approximate the ratio.
- Baseline rehearsal uses only a validation partition within the training set. Final test labels do not go to the advice model.
- GPT-6.1 Sol advice with medium reasoning; draft review with high reasoning, if configured. A clearly labelled rules-only mode remains usable without a key.
- Advice cannot change hard checks. Questions are limited and linked to missing evidence.
- No claim that a passed check proves absence of leakage. Scientific approval, fresh private labels, and an isolated execution service remain separate requirements.

## Completion evidence

- Unit and API tests for splits, exports, access boundaries, invalid input, edits, and persistence.
- Real HTTP journey from brief and CSV to both packages and participant preview.
- A real model call if credentials are available, with a small bounded output budget.
- Browser inspection at desktop and mobile sizes.
- Research report, setup instructions, validation record, and working local URL.
