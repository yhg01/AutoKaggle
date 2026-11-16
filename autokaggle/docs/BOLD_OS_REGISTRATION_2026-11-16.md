# BOLD OS registration check — 16 November 2026

The new token exposes acting tools. Automatic live Problem Bank registration is still blocked by the missing receiver deployment.

## Live findings

- The live MCP `tools/list` request returned HTTP 200 and 26 tools, including write actions. The new approval is visible to the service.
- The catalog contains neither `register_benchmark` nor `list_benchmarks`.
- The configured registration route returned HTTP 404. No production problem was created.
- [BOLD OS PR #31](https://github.com/bold-lab-ai/bold-os/pull/31) remains open for Eduardo's review. This test did not merge or deploy it.
- The design uses one Problem Bank page. Evaluator versions are stored under each problem. A separate Benchmarks page is not required.

The token stays in private configuration. It is absent from source, test reports, screenshots, and participant files. Civo's write connection remains disabled.

## Defect corrected

Publishing a checked evaluator previously called the sender before human approval. With an active connection, it could register the earlier software stage automatically. The receiver supports those stages, but the agreed AutoKaggle workflow requires research validation and human approval before automatic registration.

The sender now records `awaiting_approval` and sends nothing until approval matches the exact commit, contract, and research report. It also rejects configuration that allows unrestricted email access to use the shared write token. The approval view explains the destination, record contents, and lab visibility. Successful registration adds a direct Problem Bank link.

## Browser and integration test

The isolated Lite prototype ran at port 18884. The BOLD OS test site ran at port 8150, with local Firebase Auth, Functions, and Firestore emulators. Normal email-code routes used local mail capture. This did not test email delivery.

The session was named **TEST ONLY — Problem Bank registration 16 Nov**. Its release, GitHub address, and research evidence were synthetic fixtures. They tested registration state handling; they did not establish research validation or a downloadable evaluator release. A test transport routed only that fixture to the real local receiver. Production tokens were not used in the emulator.

Observed results:

1. The evaluator view showed **Awaiting approval** before the browser approval action.
2. The missing storage-notice record in the fixture correctly blocked the first action. The test setup was completed before proceeding.
3. The browser approval action sent the registration automatically. The receiver returned HTTP 200 and Lite showed **Registered**.
4. The BOLD OS page displayed the problem, owning project, evaluator commit, evidence stage, human approval, and session links.
5. Two duplicate deliveries returned the same receipt. Firestore retained one problem, one evaluator version, and one registration history entry.
6. An unauthenticated registration request was rejected.

The fixture's links point to example assets and a local session. They are not usable production downloads or production session links. No real research data were used or uploaded.

## Automated and model checks

- 53 Python tests passed across the registry, research-release, and OS connector modules.
- 57 Lite UI tests passed, including approval disclosure and the fixed-origin receipt link.
- 17 BOLD OS registry tests passed, including project ownership, acting access, evidence validation, retry handling, and version history.
- A live `deepseek-v4-pro` interview response took 9.5 seconds. It preserved every accepted contract field and correctly reported that registration remained unavailable until receiver deployment. It made no research-validation or publication claim. This was a model API check; the approval and registration path was checked separately through the browser.

DeepSeek was used under the owner's temporary provider instruction. No OpenRouter coverage is claimed.

## Remaining activation steps

1. Complete Eduardo's review of BOLD OS PR #31. Merge the page and deploy the `boldApi` and `benchmarkRegistry` functions plus the associated Firestore rules through the BOLD OS release process. Do not deploy unrelated Firebase services.
2. Review and deploy the AutoKaggle approval fix. Use approved member access or a tested Slack/BOLD identity connection before enabling the shared token.
3. Set the fixed registration endpoint and approved acting token in Civo's private configuration. Keep them outside evaluator jobs and participant packages.
4. Test one genuinely validated, human-approved evaluator on the live system. Confirm its receipt and Problem Bank entry, then retry once to check uniqueness.

The current automatic sender is attached to the Lite evaluator release workflow. The Full interview does not gain an equivalent registration hook from this change. Generic model write tools, project creation, and skill publication are also outside this test.
