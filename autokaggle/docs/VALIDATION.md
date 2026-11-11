# Validation

## PR #13 integration with main — 6 November 2026

The combined researcher-name feature and current main passed 1,228 Python tests, 204 Node client tests, and the English source check. Three expected Python warnings came from invalid prediction classes and numeric overflow. New regression checks preserve both names and pending environment approval status in admin searches. Login and profile checks preserve the agent as the default and retain explicit challenge-review destinations. Unicode test names use escapes to meet the repository source check; the tested values are unchanged.

Two real OpenRouter calls used `openai/gpt-6.1-sol` with medium reasoning. Named organizer and collaborator replies passed. The check also confirmed shared member names, admin search and correction, denial of unauthorized changes, account continuity after sign-in, and exclusion of profile names from model input. The test used a temporary store and captured local mail. It did not test Gmail delivery or change production data.

A separate backend review found no blocking issue. A new visual browser check could not run: the browser permission gate denied access to the temporary local test page. Earlier browser results below describe the earlier branch only. This integration was not deployed to Civo.

## Thirty model requests per round — 3 November 2026

The interview and revision limit is now 30 model requests per round. Failed requests and automatic response repairs count toward that limit. The eight-follow-up checkpoint and lifetime call accounting remain in place. Limit messages use the configured constant. The separate legacy workbench advice limit remains 12 requests per project.

Validation passed 1,135 Python tests, 157 Node client tests, and the English source check. Boundary tests cover requests 13 and 30, exhausted retries, use of the final request for repair, and continuation with a fresh round. Two live OpenRouter calls used `openai/gpt-6.1-sol` with medium reasoning. Requests 13 and 30 processed the correction and preserved independent facts. A subsequent answer made no model call, stayed saved for review, and produced the 30-call limit notice. The prior request count was seeded in temporary fixtures; the live check made two actual requests. Reports stay in the ignored test-results directory. This local verification did not deploy the change.

The change was then deployed to the AutoKaggle Civo service as source `1218337455b67b9a1d759f2e3c119d991facef146f25988742f563caf77944e8`. The rollout and SQLite backup integrity checks passed. All 27 project records match their pre-release hashes, and the service retains 14 email accounts. The running conversation API reports 30. HTTPS health and login checks passed, anonymous Internal access was denied, and email login remained configured. One further live OpenRouter call ran in the deployed container with a temporary in-memory fixture whose counter was seeded at 29. Request 30 completed, and the next answer stopped without another model call and remained saved in that fixture. No production project was written by this model check. See the deployment record in `autokaggle/deploy/WEB.md`.

## PR #12 and PR #9 merge checks — 3 November 2026

The combined changes passed 1,133 Python tests, 157 Node client tests, and the new English source check. Three expected warnings came from invalid prediction classes and numeric overflow.

Merge review found that PR #9 could reopen a confirmed scope after an appended unknown or compatible detail. Requirement reassessment now needs a validated correction that replaces source evidence for that specific decision. Seven new cases cover compatible additions, questions, unknown answers, and preservation of unrelated confirmed decisions. The existing correction fixture now supplies the exact replacement operation required by the prompt.

Live OpenRouter checks used `openai/gpt-6.1-sol` with medium reasoning. Five real model calls passed. The recovery script checked the reported kernel correction, preserved independent parameters, sign-out and sign-in, interrupted-answer retry, and required setting controls. Three further calls checked a correction without the former keywords, a question that leaves the prior choice intact, and an added detail that preserves confirmed scope. Email used a captured local transport. No hosted scientific session was changed and no production deployment was tested. Reports stay in the ignored test-results directory.

## Researcher names — 3 November 2026

The name feature passed 1,147 Python tests and 171 Node client tests. Three expected warnings came from invalid prediction classes and numeric overflow. New checks cover existing account migration, Unicode names, duplicate names, sign-out and sign-in, stale forms after account changes, CSRF protection, admin access, search across all project pages, collaborator labels, and exclusion of profile names from participant packages. Naming an account leaves its saved scientific records unchanged.

Live OpenRouter validation used `openai/gpt-6.1-sol` with medium reasoning. Two real model calls passed: one organizer reply and one collaborator reply. The check also confirmed named message authors, shared member names, admin search and correction, access rejection for another researcher, and stable account identity after sign-in. Profile names were absent from the model input. Run `python -m autokaggle.scripts.live_researcher_names_verify` to repeat this check with the private root `.env` file.

Browser checks used a temporary local store at 1280 × 720 with captured local mail. They covered the first name prompt, return to the same challenge, Profile editing from Sessions, admin name search, admin correction, and return from Profile to the same selected admin project. No browser warnings or errors were observed. Screenshots and reports stay in the ignored test-results directory. This run did not test live Gmail delivery, small-screen layout, or a production deployment. Production researcher profiles were not changed.

## PR #3 merge checks — 3 November 2026

The PR #3 integration with current main passed 1,125 Python tests and 157 Node client tests. Three expected warnings came from invalid prediction classes and numeric overflow. The tests cover setting choices at checkpoints, rejection of unrelated setting choices, retry identity, storage acceptance, answer reassessment, and expired sign-in with the session dialogs.

Live OpenRouter validation used `openai/gpt-6.1-sol` with medium reasoning. The recovery script passed in two calls. A separate checkpoint check passed in three calls: an explicit Chinese code-submission choice was saved, an explicit Chinese allowance of three was saved, and a bare yes without a pending proposal left the competition type unset. Reports stay in the ignored test-results directory.

Browser validation used a temporary local store and captured local mail. It checked the storage notice, the Sessions dialog, and a private session request after the test account expired. The dialog closed and exposed a sign-in link back to the same project. No production deployment or Gmail delivery was tested. PR #9 was not included.

## Interview and sign-in recovery — 2 November 2026

The recovery change passed 1,063 Python tests and 149 Node client tests. Three expected warnings came from invalid prediction classes and numeric overflow. New checks cover natural negative corrections, preservation of unrelated facts, checkpoint messages and deferral, targeted scope review, interrupted server flags, saved-answer reassessment, bounded status polling, reconnection without a model retry, and expired sign-in.

Read-only inspection of the hosted conversation matched the screenshot and confirmed the correction-validation failure. The owner then supplied the second session link. It was idle with a completed, accepted model response and no pending answer. Its required competition choice was unresolved, but the checkpoint directed the researcher to scope controls that cannot accept server-owned settings. Signing in restored that unresolved checkpoint. No hosted conversation was edited. The inspected deployment reported no container restart. See [Interview checkpoint and session recovery](INTERVIEW_RECOVERY.md) for the findings and all changes.

The final live OpenRouter check passed in two real `openai/gpt-6.1-sol` calls with medium reasoning. A temporary kernel fixture accepted the reported “don't use top hat” correction, retained the independent Fourier parameters, signed out and back into the same account, recovered an interrupted answer, reassessed saved replies, and verified retry identity. Explicit checkpoint deferral kept the scientific requirement incomplete. The test used the normal email-code/account path with captured local mail and no resend delay. It did not test Gmail delivery.

Live browser testing used a separate temporary store and two further real model calls. It recovered an interrupted correction through the visible Retry saved answer control, signed out and back in, resumed the same conversation, and submitted another answer successfully. An expired local session also exercised the private-project 404 path. The data dialog closed and exposed a sign-in link back to the same project. The recovery banner fitted a 390 × 844 viewport without horizontal or document overflow. No browser warnings or errors were observed.

```sh
python -m autokaggle.scripts.live_interview_recovery_verify
```

The follow-up setting fix passed 1,069 Python tests and 152 Node tests. The extended live script passed in two medium-reasoning model calls. It also reopened the two required setting checkpoints and recorded code submissions and five daily submissions without another model call or a bypass. Browser testing signed in at the competition checkpoint, selected code, rejected an invalid zero allowance, and confirmed five submissions. An explicit synthetic definition fixture supplied the other scientific decisions. The resulting draft used one real high-reasoning model call. These seeded facts do not establish completion of a human interview. The mobile page fitted 390 × 844 with internal conversation scrolling and no document overflow.

That browser draft exposed a repeated request for the already-recorded organizer email. The model context withheld the address without stating that contact was recorded. A boolean status and prompt rule now supply that information. A further live high-reasoning draft call passed in one model call: its context contained the true status without the address, and its next actions did not request the email again.

Reports and screenshots are retained only in the ignored local test-results directory. This change has not been deployed by this verification run. It does not establish scientific completeness, live email delivery, or recovery of the hosted sessions after deployment.

## Research session controls — 2 November 2026

The session-controls PR passed 1,084 Python tests and 142 Node client tests. Three expected warnings came from invalid class and numeric inputs. These checks cover storage acceptance, session access and deletion, backup restore filtering, handoff expiry and revocation, answer removal and replacement, request retries, preserved submission quotas, source import limits, and free-form compute estimates. They also verify that rejected creation requests store no research content and that leaving a shared session revokes submission tokens.

Live checks used OpenRouter with `openai/gpt-6.1-sol`. The source, collaboration, and erasure test passed in four real model calls with medium reasoning. It retrieved the SPOCK 2.0 paper and the public SPOCK repository, required approval before adding a proposed brief, recorded hardware-time and token estimates, replaced a researcher answer, checked retry behavior, revoked collaborator access, and deleted its temporary session. The repository was frozen at commit `05beb10ae06f3c66a7bd018e430645b91287436e`. Imported code was not executed.

A separate live revision test passed in three model calls. Draft generation used high reasoning; revision used medium reasoning, including one bounded response repair. It started from an explicitly seeded synthetic challenge definition, built a research package, scored a real development prediction file, and revised the compute estimate with that measured result in context. The saved target and metric remained intact. This check establishes revision after a scored attempt; it does not establish completion of the scientific interview or reproduction of a scientific reference method.

One further live call checked the organizer-advice prompt with medium reasoning. Its evidence-validated updates preserved `A100 x8 x24h` and `2M tokens` without requiring or inventing dollar estimates.

Live browser testing used a temporary local store. It covered storage acceptance, session creation and switching, a real paper/repository import, approval of an edited starting brief, a real interview reply, answer-edit controls, and session, sharing, revision, and deletion dialogs. The final source proposal was limited to 2,200 characters and generated in one live call; the approved brief then produced an interview reply in one further call. Testing found an answer-edit button that stayed disabled after a reply. The fix passed a client regression test and a browser recheck. The page had no horizontal or document overflow at 390 × 844. Session tools scrolled inside their dialog. No browser warnings or errors were observed.

To repeat the live checks, load the private OpenRouter key from the repository-root `.env` and run:

```sh
python -m autokaggle.scripts.live_workspace_verify
python -m autokaggle.scripts.live_iteration_verify
```

Reports and screenshots remain in the ignored local `autokaggle/test-results/` directory. These tests did not send email, deploy to Civo, execute submitted code in a live sandbox, or change production data. Session deletion does not erase separate sign-in account records or physically remove historical backup copies. The operator must follow the backup and erasure procedures in [Research session controls](WORKSPACE.md).

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

Researcher-requested lookups have their own live check. It uses isolated sessions and neutral material, and checks that nothing is looked up without a request, that a finding is recorded only after acceptance, that a rejected finding stays out, that a question is not counted as a failed clarification, and that instructions inside a document are not followed:

```sh
python -m autokaggle.scripts.live_lookup_verify --runs 2
```

Browser checks during the scope release covered acceptance, reload persistence, explicit exceptions, removal, and a checkpoint after two attempts. The checkpoint browser test used a seeded local state. The deployed scope editor was inspected without saving a change to the existing organizer project.

## Hosted release and private operational records

The scope release on the BOLD Civo site passed rollout and HTTPS health checks. Email login remained available after deployment. Earlier hosted email checks verified actual code receipt, sign-in, sign-out, and restoration of the same private account. Delivery to other email providers and a real organizer review invitation were not tested in that run.

Deployment receipts, screenshots, temporary project records, and uploaded datasets are not included in this source repository. Operators must generate and retain their own private verification records. A new checkout has no authority to execute code merely because an earlier BOLD installation passed checks.

## Limits

The current trial validates the submission and scoring pipeline with a simple predictor. It does not reproduce a scientific reference baseline. Dataset links are not automatically imported. Hosted code execution, the requested public/private leaderboard workflow, and public competition launch remain outside the delivered hosted flow. See the [current implementation](../README.md) and [future work](FUTURE_BACKEND.md).

## Environment evaluation — 4 November 2026

Tested in an isolated checkout and temporary stores. Not deployed.

- Live model: OpenRouter `openai/gpt-6.1-sol`, medium reasoning. A researcher answer that names a checkpoint, a GitHub repository, and held-out seeds selected the environment format. The next question did not ask for a CSV, target column, or row split. Script: `autokaggle/scripts/live_environment_verify.py`.
- Live GitHub: the NLE repository was pinned to one commit. A repository without the manifest was refused and did not use the allowance.
- Package: the shipped harness ran the shipped example policy as a real process against a toy environment.
- Manual approval: a complete environment draft waited for approval with no review email or link. The local browser check approved a synthetic draft in Internal, after which a test double received the organizer email. A repeat approval was refused.
- Private repositories: automated tests cover the service credential, including that a redirect to another host never receives it and that source imports never use it. A missing repository on live GitHub returned the access message and used no allowance. No credential exists yet, so a private repository was not read from real GitHub.
- Upgrade: synthetic records written by the deployed source were read by the new source and then by the deployed source again. Only a record marked as replying changed at startup, which is the existing interruption recovery. The built draft showed as out of date until rebuilt, as designed for a generator change. An environment challenge stayed readable after rollback, and its rebuild reported needs_changes.
- Browser: format selection, seed form, range error, commit pin, draft build, website, repository submission errors, and submission token, on a local server.
- Not tested: the NLE environment was not run. No GPU evaluation was run. The successful manifest read was simulated because no public repository has the manifest yet. Results were recorded from synthetic episodes. Review email used a test double. The hosted service was not changed.

## Organizer review workbench — 4 November 2026

Tested in the isolated `codex/organizer-review-workbench` checkout, on top of the environment changes described above. The combined release was deployed to Civo on 4 November 2026. The deployment record is in `deploy/WEB.md`.

Normal entry links, old workbench links, and normal sign-in returns open the interview. An explicit Review action opens the workbench only when a built challenge version exists. Account checks still apply. Opening review does not create a project, call a model, start a revision, or approve an environment draft. Legacy participant pages remain available.

The regression suites passed 1,202 Python tests and 179 Node tests. Three expected warnings came from invalid class and numeric inputs. The tests cover routes, account access, navigation, stale packages, safe artifact links, preserved context and measured results, duplicate requests, interrupted replies, expired access, and late responses after an account change.

Live OpenRouter checks used `openai/gpt-6.1-sol`. The API check made two real calls. The browser revision made two more: a scope call with medium reasoning and a draft call with high reasoning. These checks started from a seeded scientific definition and a measured CSV pipeline test. They establish the review and revision path, not a complete scientific interview. The revised compute budget was saved while the target and metric remained unchanged.

The desktop browser test covered sign-in, overview, definition details, checks, trial results, an old workbench link, explicit review entry, a request for changes, a model reply, stale artifact links, and a successful rebuild. The rebuilt version restored its website, package, and submission links. No browser warnings or errors were observed. The viewport was 1280 by 720 pixels. A mobile viewport was not tested.

The live check can be repeated with a private root `.env` file:

```sh
python -m autokaggle.scripts.live_workbench_verify
```

Reports, logs, and the overview screenshot are in the ignored `autokaggle/test-results/review-workbench/` folder. Email used a local test receiver. No real Gmail message was sent. No production records, hosted runner, or Civo deployment were changed.

### Hosted release verification

After the owner authorized deployment, a fresh live OpenRouter revision check passed with two calls: medium reasoning for scope and high reasoning for the draft. The Civo rollout then passed readiness, public health, email-login availability, old-link redirects, explicit review sign-in, and denial of anonymous Internal access. The deployed workbench JavaScript and CSS match the local source exactly. A desktop browser check confirmed that the hosted sign-in page loads after the rollout.

The database backup passed `PRAGMA integrity_check`. After the rollout, all table counts matched and all 29 saved project bodies had the same hashes as before. The data volume, credentials, application configuration, and other Deployment fields were preserved. Four built drafts were already stale before deployment. No researcher record was edited, and no email was sent by these checks. The detailed receipt is an ignored private operational record.
