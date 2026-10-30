# Validation

The standalone source snapshot was checked on 30 October 2026. These results describe the tested behavior. They do not establish scientific validity for a new challenge.

## Model response recovery — 30 October 2026

The response schema now declares the same text and array limits as the server. Invalid question formatting is replaced with an open checklist question after factual validation. Invalid structure or evidence gets one automatic repair call per action, within the existing call budget. Rejected facts remain unapplied. Private diagnostics retain fixed failure codes only.

The final automated checks passed 1,030 Python tests and 122 Node tests. Three expected warnings came from invalid class and numeric inputs. Live OpenRouter verification used GPT-6.1 Sol with medium reasoning. A three-turn SPOCK interview recovered from one deliberately invalid evidence excerpt in four model calls. Repeating each request ID added no messages or calls. Three additional calls verified that scope acceptance survives new information and that a correction reopens only the affected decision.

A live browser test changed one real model response to contain an oversized question and an invalid checklist reference. The interview continued after one model call, kept the valid facts, and showed the next checklist question. No browser warnings or errors were observed. These checks establish response recovery; they do not establish the scientific validity of the challenge. The old failure handler did not retain its validation reason, so the exact cause of the earlier reported error is unknown.

To repeat the live evidence-recovery check, place the private OpenRouter key in `.env` and run:

```sh
python -m autokaggle.scripts.live_response_verify --inject-evidence-error
```

The fault is applied only in the isolated verification script. Production never changes provider replies in this way. Reports are saved under ignored `autokaggle/test-results/`.

## Automated checks

- 1,030 Python tests passed from the standalone checkout.
- 122 Node client tests passed.
- Three expected warnings came from tests for unknown prediction classes and numeric overflow.

```sh
python -m pytest autokaggle/tests -q
node --test autokaggle/tests/test_chat_ui.cjs autokaggle/tests/test_login_ui.cjs autokaggle/tests/test_review_ui.cjs
```

Coverage includes interview evidence, scope decisions, targeted corrections, the two-question limit, draft and revision state, package versions, data checks, scoring, quotas, retries, account access, email-code handling, and client error recovery. Runner tests use controlled transports; unit tests do not establish live cluster isolation.

## Live model and browser evidence

The scope workflow was tested through OpenRouter with `openai/gpt-6.1-sol`, using medium reasoning and an isolated synthetic planetary-system problem. The test checks focused questions with practical reasons, scope acceptance, retry behavior, preservation after compatible new information, and selective reopening after a correction.

Run the live test with a private `OPENROUTER_API_KEY` in the repository-root `.env`:

```sh
python -m autokaggle.scripts.live_scope_verify
```

The script writes a report under ignored `autokaggle/test-results/`. It makes real API calls and incurs provider usage.

Browser checks during the scope release covered acceptance, reload persistence, explicit exceptions, removal, and a checkpoint after two attempts. The checkpoint browser test used a seeded local state. The deployed scope editor was inspected without saving a change to the existing organizer project.

## Hosted release and private operational records

The scope release on the BOLD Civo site passed rollout and HTTPS health checks. Email login remained available after deployment. Earlier hosted email checks verified actual code receipt, sign-in, sign-out, and restoration of the same private account. Delivery to other email providers and a real organizer review invitation were not tested in that run.

Deployment receipts, screenshots, temporary project records, and uploaded datasets are not included in this source repository. Operators must generate and retain their own private verification records. A new checkout has no authority to execute code merely because an earlier BOLD installation passed checks.

## Limits

The current trial validates the submission and scoring pipeline with a simple predictor. It does not reproduce a scientific reference baseline. Dataset links are not automatically imported. Hosted code execution, the requested public/private leaderboard workflow, and public competition launch remain outside the delivered hosted flow. See the [current implementation](../README.md) and [future work](FUTURE_BACKEND.md).
