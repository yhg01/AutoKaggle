# BOLD AutoKaggle onboarding

An agent interviews the researcher and turns the answers into a private challenge draft. It follows the [Kaggle workflow](../AGENTS.md) and uses the [interview guide](docs/README.md) to choose relevant follow-up questions.

The [private Civo portal](https://ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/) has HTTPS and persistent storage. Email sign-in gives each verified address its own private workspace; administrator access remains separate. Email sign-in is deployed through the Gmail API and passed a real inbox, sign-in, sign-out, and return-session test. Delivery was tested only to the sender Gmail inbox. See the email verification record (local operational record; not included in this repository). Invited reviewers can access one assigned challenge. The website, ZIP, and prediction submission routes are available after the challenge passes its build checks. See [deployment and access instructions](deploy/WEB.md). The hosted code controller remains disabled. This deployment does not resolve the recorded SPOCK revision failures.

## Selected MVP scope

The selected scope is types **1, 2, 3, 5, and 7** from the [Kaggle competition survey](https://docs.google.com/document/d/1AgYAYdeTC3tQ0yzlzqvLBFnRKJoJDts4NjCBTZtKQq8/edit), approved on 29 October 2026.

| Type | Required evaluator | Current status |
| --- | --- | --- |
| **1. Classic prediction** | Validate an uploaded prediction file and score it against private answers. | Development scoring and quotas work. Hidden public/private membership and final ranking remain pending. |
| **2. Code with hidden inputs** | Run frozen code on Civo; send predictions to a separate trusted scorer. | A bounded Python runner works. Full competition lifecycle and broader scientific environments remain pending. |
| **3. Code with an inference API** | Supply one approved input or batch at a time; validate each response. | Pending. The current runner supplies a complete input file. |
| **5. Live forecasting / future data** | Freeze entries, collect later inputs and outcomes, then evaluate those entries. | Pending. There is no future-data collection or release cycle yet. |
| **7. Optimization** | Check solution feasibility and compute a deterministic objective. | Pending. Current scoring expects classification or regression targets. |

These workflows share one challenge lifecycle. Submission format, evaluator type, and holdout policy are separate settings. For example, future-data evaluation can use the code runner or an inference API. Optimization does not require a labeled training set when feasibility and an objective define success.

The proposed build order is **1 + 2 → 7 → 3 → 5**. Complete the common submission and leaderboard lifecycle first. Then add objective scoring, controlled sequential inputs, and future-data collection. Preserve the compact chat and ask only for missing, relevant decisions. The [backend plan](docs/FUTURE_BACKEND.md#selected-mvp-delivery-order) defines the completion checks. Other survey types are deferred.

## Use it

1. On the hosted site, sign in with the six-digit code sent to your email. The verified address fills the private organizer contact for a new challenge. Local mode or an existing draft can still request the correspondence email. Then answer the agent's opening question. Share any research brief, data description, known method, or useful result. A complete specification is not required to start.
2. The agent records the supplied facts and asks one focused question about the next missing decision. A visible checklist has four sections: **Problem**, **Method & deployment**, **Baseline**, and **Setup**. Select section 4, **Setup**, for organizer settings. Select any section to see its items. Select an item to inspect its recorded answer and remaining gap.
3. Reply in ordinary language. For a dataset, provide a source link, or upload a CSV file up to 200 MB through **Data & checks** at the bottom left. The standard is a Google Drive file or folder shared as **Anyone with the link**, with the **Viewer** role. Direct dataset URLs and repository links also work as source references. For generated data, describe the setup and give a code or documentation link if available. State unknowns, select **Not sure yet** to defer a decision, or correct an earlier answer. The agent collects competition type and daily allowance through chat when needed. Five submissions per team per UTC day remains a proposed default until confirmed.
4. Select **Create draft** when ready, including when some questions remain open. Use **Draft & package** to review and download the challenge README. Return to **Conversation** to make corrections.
5. Use **Data & checks** when the scientific definition is ready for a trial. Attach a supported CSV and set its target, metric, and split. Run the available data and baseline checks, then build the review package in **Draft & package**.
6. Review the website draft, research ZIP, schemas, versioned metric, dependency record, resource contract, and manifest. The ZIP includes the challenge README and participant `AGENTS.md` instructions for research, validation, submission, and reproducibility. Missing data or required decisions stay visible and prevent readiness. The current trial tests the submission pipeline with a constant predictor and checks the scorer with perfect answers. These checks do not reproduce a scientific reference method.
7. Open **Review** to use the website, download the research ZIP, and test a prediction CSV. Python submissions require the verified local controller; the hosted web service keeps them disabled. The API enforces the daily quota, including invalid files, and reuses the result for a retry with the same request ID.
8. Select **Request changes** to start a revision chat. It asks what should change in the problem definition, method and deployment, or baseline reproduction. Previous messages, facts, and trial results remain available. The agent asks focused questions about your request. Create a revised draft, then rebuild its artifacts and review the new results.
9. The hosted service has [Gmail API delivery](docs/EMAIL_SETUP.md) configured. Civo blocks SMTP by default; the sending connection uses HTTPS and is separate from Drive access. A ready draft can send one single-use login link and authenticated links to A, B, C, and the revision chat. The login opens the review page. Real email-code delivery passed; no real review invitation was sent in this verification run. Public launch remains a later step.

The page fits the viewport. Conversation history and README text scroll inside their panels. The composer and main actions stay visible.

**Within the agreed scope, another research agent can implement an attempt and interpret its score without inventing scientific assumptions.**

Each checklist item has explicit requirements. The bars count resolved requirements, with evidence and remaining gaps. They do not measure the accuracy of scientific claims. Every applicable requirement outside the reference baseline is compulsory unless the organizer records a manual bypass. Unknown and deferred required details remain blockers. A conditional requirement can be marked not applicable only with a recorded reason.

If the recorded detail matches your intended scope, open the checklist card and select **Accept this scope**. Edit the summary, then review the remaining decisions it will confirm. You can assign an allowed implementation choice to the research agent with explicit limits, or record an unresolved scientific assumption as an exception. These decisions stay distinct in the card and exported package. Removing scope acceptance restores the underlying evidence assessment. A later correction reopens only the affected decision. Rebuild the package after changing scope.

The agent checks saved answers before it asks again. Each question explains the consequence of the missing decision. After two unsuccessful clarification attempts for one requirement, a checkpoint offers scope resolution. A new round does not silently restart the same questions.

The server repairs invalid question formatting with a checklist question after it validates the recorded facts. An invalid response format or unsupported evidence receives at most one automatic model repair per action. This call counts toward the existing 12-call limit. The repair uses the same saved answers and a fixed explanation of the validation failure. No partial facts from the rejected response are applied. Network errors still offer a manual retry. Repeated requests with the same request ID do not add messages or model calls.

If the agent cannot complete a requirement after your explanation, open its checklist card. In the details, select the requirement's manual bypass option and enter a reason. The bar then counts that requirement as resolved and shows **Manually bypassed**. Its source facts remain available. You can change the reason or remove the bypass. Removal restores the current evidence assessment. A bypass records an organizer exception; it does not establish missing facts. The reason appears in the challenge README, participant `AGENTS.md`, `challenge.json`, and organizer review. Rebuild the package after any bypass change before requesting review.

Bypasses apply to interview requirements. Email, competition type, and the daily allowance need validated values to operate the service. The optional baseline needs no bypass. Data, scorer, submission, runner, and access checks remain mandatory.

A scientific reference baseline is optional. New problems without a functional baseline can become ready when all other required details are resolved and technical checks are complete. Scorer checks and a valid submission pipeline test remain mandatory. A working draft can contain gaps, but unresolved requirements prevent review readiness and invitations. `challenge.json` and the packaged README record the definition status, required gaps, manual bypass reasons, and optional reference status.

## Start locally

Use Python 3.11 or later. From the repository root:

```sh
python3 -m venv autokaggle/.venv
autokaggle/.venv/bin/pip install -r autokaggle/requirements.txt
autokaggle/.venv/bin/python -m autokaggle.run --env-file /absolute/path/to/private.env
```

The private environment file needs `OPENAI_API_KEY`. Open <http://127.0.0.1:8877/>.

The local server binds to localhost. Keep its private environment file outside source control. See the [repository setup instructions](../README.md#start-locally) for a clean installation.

## How it behaves

- The agent leads the interview. It reads the complete reply before asking one relevant follow-up. Eight follow-ups end a bounded round. This checkpoint preserves the gaps and allows another round; it does not establish readiness.
- Dataset questions ask for source links. The agent reuses links already supplied and accepts unknown or unavailable links without repeated requests. It does not request full dataset uploads through chat. A link does not prove permission, access, inspection, or import.
- Three topic summaries make the interview visible. The internal guide has 17 items, including methodology and deployment. Existing conversations retain their recorded answers and messages.
- Recorded, partial, and deferred answers stay distinct. Unknowns appear in the README. Corrections preserve facts that were not changed.
- Methodology, submission artifact, deployment setting, and evaluation procedure remain separate. The agent asks about the information available to the deployed solution and how its output produces the desired result.
- Optional reference baseline information includes the strongest known method, reported performance, sources, and reproduction requirements. A reported score stays separate from an actual measured run. No functional reference is required for a novel problem. Automatic literature research and reproduction of arbitrary reference methods are not implemented.
- Trial execution belongs to the application. The agent does not ask the researcher to provide proof that the application ran a baseline. It cannot mark a data audit, scientific review, or reproduction as completed from conversation alone.
- The README body uses the saved answers. Model suggestions are labelled separately.
- Each interview round and revision has a 12-call limit and at most eight follow-ups. Failed calls count. Explicit retry preserves the original message. Required gaps remain open at the limit. The project also keeps its total call count. A revision starts only when the organizer requests it from a saved draft.
- Local chats and drafts are saved in `autokaggle/data/`; Civo uses its persistent volume. The browser stores unsent text and a private session cookie. Email sessions last up to 30 days. Signing in again restores the same account. Sign-out revokes the session and clears cached drafts. Account workspaces remain separate.

The current AutoKaggle app records dataset links as text. It does not download or inspect linked data, including Google Drive files. A link alone cannot complete the data or baseline checks. The [data workbench](docs/WORKBENCH.md) remains at `/workbench` for CSV checks. The draft workflow supports classification and regression with the five existing metrics. It accepts the existing bounded CSV format (200 MB, 1,000,000 rows, 200 columns, ten million cells). The file-size limit is 209,715,200 bytes. For larger files, paste a Google Drive link in the interview with **Anyone with the link** access and the **Viewer** role. Links are saved for review; automatic import is not yet available.

The current implementation uses an outer split of 80% training pool and 20% final test. Development validation is taken from the training pool. Its labels remain private so repeated development submissions have a meaningful score. Prediction packages include separate development and final input files. Code packages include training data and representative inputs; actual development and final inputs remain private. No package contains private answer files. The project instructions now specify a 70/30 training/test policy; that runtime change remains pending.

The local operator service can run code submissions in the dedicated Civo sandbox. The hosted web service has no controller credentials and keeps code execution disabled. Local execution requires passing runtime and controller checks, plus current cluster controls. The preview accepts one Python file with standard-library dependencies, 1 CPU, 512 MiB RAM, 90 CPU seconds, 100 program seconds, and a 120-second Job deadline. Storage preparation and cleanup can take several minutes. Scientific package images and GPU execution need further work. See the [cluster evidence and operating limits](deploy/README.md). The website template is a private review draft.

Email codes expire after ten minutes and work once. Any verified address can create a private workspace. This is an MVP access choice, not a claim about Kaggle authentication. Review links remain separate: they expire after 24 hours and grant access to one project for seven days. The private preview can issue a submission-only token for `submit.py`; it grants no organizer or private-data access. Preview tokens share one team allowance. Public team registration, final scoring release, GPU jobs, and public competition deployment remain future work. The local server binds to localhost.

## Public and private leaderboards

This is the required competition design. The current development scorer does not yet implement these leaderboards.

This section describes a fixed labeled test pool. Live forecasting instead needs a submission cutoff and later data. Optimization uses feasibility checks and an objective; it can use public/private problem instances when hidden-instance generalization is part of the task.

Kaggle separates two decisions: which rows are training/test data, and which test rows determine public/private scores. The host's `solution.csv` holds test answers and a `Usage` assignment. `Public` means its score can be shown during the competition; its answers still stay private. `Private` supplies the final ranking. [Kaggle setup guide](https://www.kaggle.com/docs/competitions-setup).

For a prediction competition with 30 test rows and a 50/50 leaderboard split:

| Stage | Participant action | Score shown |
| --- | --- | --- |
| During the competition | Upload all 30 predictions in one file | Aggregate score on 15 fixed public rows |
| Before the deadline | Select eligible saved submissions for final ranking | Public scores only |
| After the deadline | The evaluator uses the frozen selected predictions | Final score on the other 15 private rows |

Participants do not receive the row-to-subset mapping. The split fraction can differ from 50/50. A standard prediction competition needs no replacement prediction file after closing. Kaggle's rules define final submissions as entries selected by the participant, or selected automatically when required. The permitted count depends on the competition. [Example competition rules](https://www.kaggle.com/competitions/the-new-era-of-competition/rules).

Code competitions can execute a saved code version against hidden inputs. Freeze its code, model assets, and environment before final evaluation. This is an evaluator run of the selected entry. It does not permit a new model after private feedback. Kaggle also restricts hidden-run logs because they can expose host data. [Kaggle staff explanation](https://www.kaggle.com/product-feedback/121112).

AutoKaggle onboarding must record the public/private fraction, split method, daily allowance, score precision, final-entry count, fallback selection, deadline, and release conditions. Training-derived validation stays available for local model selection. The two leaderboard subsets belong to the held-out test pool. Their membership must stay fixed and private across all teams and attempts. Exclude identifying prefixes, separate subset files, and reproducible membership seeds from the research ZIP.

This limits overfitting to repeated public feedback: private outcomes cannot guide changes before the entries are frozen. It does not make an existing public answer key secret. Public source data still need checks for answer exposure and leakage.

**Implementation gap:** current prediction packages expose development and final inputs separately, and the API returns development scores only. Hidden membership, combined test submissions, final-entry selection, and leaderboard release are pending. This documentation change does not enable them.

## Checks and references

Run `python -m pytest autokaggle/tests -q`, `node autokaggle/tests/test_chat_ui.cjs`, and `node autokaggle/tests/test_review_ui.cjs`. Each test run must also include live OpenRouter validation of the affected model workflow, as required in [AGENTS.md](../AGENTS.md#live-api-testing). Unit tests alone do not establish live model behavior. See the [validation record](docs/VALIDATION.md), [API contract](docs/API.md), and [research report](docs/RESEARCH.md).
