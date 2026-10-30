# Prototype interface contract

The chat is served at `/`. The earlier data workbench is at `/workbench`; participant pages remain at `/challenge/{token}`. API paths start with `/api`. JSON errors use `detail` (string or validation details).

## Private access

With private mode enabled, `/login` offers email-code sign-in and a separate
administrator option. Any verified email can create an account. Each account
owns its workspaces. The current email mechanism is an MVP choice; it does not
claim to reproduce Kaggle's internal authentication.

| Endpoint | Contract |
| --- | --- |
| `GET /api/access` | Returns `private_mode`, `can_create_projects`, `auth_kind`, `email_login_available`, and, in private mode, `csrf_token`. Sets the matching HttpOnly CSRF cookie. |
| `POST /api/access/email/request` | `{email}`. Sends a six-digit code; returns `challenge_id`, `expires_in: 600`, and `resend_after: 60`. No code is returned in the API response. |
| `POST /api/access/email/verify` | `{challenge_id, code}`. Consumes the code once, sets a private user session cookie, and returns `{redirect: "/"}`. |
| `POST /api/access/logout` | `{}`. Revokes the user session, clears identity cookies, and returns `{redirect: "/login"}`. A review-only logout removes its scoped grants. |
| `POST /api/access/login` | `{access_code}`. Retained administrator sign-in; returns `{redirect: "/"}`. |

Access POSTs require the canonical same-origin `Origin`, the CSRF cookie, and
`X-CSRF-Token` from a fresh access GET. `auth_kind` distinguishes `user`, `admin`,
`reviewer`, and `anonymous`. Configuration availability is not proof of delivery.
A missing mail connection or failed send returns 503; the client must not claim
that a code was sent.

Codes expire after ten minutes. A resend replaces the prior code and does not
reset the five-attempt limit within ten minutes. Sends are limited to one per
60 seconds, six per hour, and twelve per day per address. Global send limits are
100 per hour and 400 per day. Limits use rolling windows and persist across
restarts. A 429 response includes `Retry-After`. Invalid input returns 400, an
incorrect code returns 401, and expired, consumed, or replaced codes return 410.

User sessions last up to 30 days and can be revoked. Codes and session tokens
are stored as protected digests. HTTPS cookies are HttpOnly and SameSite. The
verified account email fills the private organizer contact for new projects.
It does not grant access to another account or to administrator-owned projects.
A scoped review invitation can grant access to an existing challenge.

## Simple onboarding chat

Create a project through `POST /api/projects`, then use these owner-only routes:

A new email-account project starts with its verified address as `organizer_email`. Where that value is absent, save a valid address through `PATCH /api/projects/{id}/setup`. Conversation writes and workflow builds return 422 until it is supplied. Existing messages remain available. Conversation JSON exposes `contact_required` for this gate.

- `GET /api/projects/{id}/conversation`: saved conversation and checklist.
- `POST /api/projects/{id}/conversation/messages`: `{message, request_id}`. Extract supported information and ask one missing question.
- `POST /api/projects/{id}/conversation/skip`: `{request_id}`. Record the current topic as deferred.
- `POST /api/projects/{id}/conversation/draft`: `{request_id}`. Build the README from known answers and open questions.
- `POST /api/projects/{id}/conversation/retry`: `{request_id}`. Explicitly retry a failed model action without duplicating its user message.
- `POST /api/projects/{id}/conversation/revision`: `{request_id}`. Start a bounded organizer revision from a saved draft. Preserve prior context and ask which changes the organizer wants. Repeating the request ID does not create another round.
- `GET /api/projects/{id}/conversation/readme.md`: current README attachment; 404 if no current draft exists.

Use a unique request ID for each action. Retry an uncertain transport outcome with the same action and ID. A model retry uses the `/retry` action with a new ID. The server serializes project writes and returns 409 for a concurrent action.

Chat JSON includes `project_id`, `title`, `mode`, `messages`, `checklist`, `current_question`, `readme`, `phase`, `status`, `error`, `can_retry`, and `followups`. Each checklist item has `id`, `label`, `pillar`, `status`, `value`, and `gap`. Status is `missing`, `partial`, `answered`, or `deferred`; an answered item records the researcher's statement, not independent verification. A conversation status of `working` means the client should poll GET before sending more input. Polling does not acknowledge a pending request: another tab can own the running action. Preserve the pending payload and retry its original request ID until its POST succeeds.

The initial brief is at most 12,000 characters. The engine asks at most eight follow-ups, then generates a draft with unresolved items. The user can draft sooner. Changes clear the previous README so downloads cannot return obsolete answers. Provider failures preserve the message and offer explicit retry or a draft from known information.

The `review` view records the mode, round, status, requested changes, clarified changes, changed fields, follow-up count, and model-call count. Revision mode keeps the full earlier transcript, a snapshot of the prior draft and recorded facts, and safe workflow checks and measured results. It asks only about requested changes. The original draft remains current until the organizer supplies new information. Each round has its own eight-question and 12-call limits. The project retains lifetime call accounting.

## Data workbench

- `GET /api/config`: `{mode: "model"|"rules", model: string, max_upload_mb: 200, max_upload_bytes: 209715200, version: string, private_mode: boolean, can_create_projects: boolean, auth_kind: string}`.
- `GET /api/projects`: `{projects: [{id,title,updated_at,status}]}` for the authenticated account or scoped organizer session.
- `POST /api/projects`: body `{title?, brief?}`; returns full project. Private mode requires an email user or administrator session. Local mode can create a secure random HttpOnly organizer cookie if needed.
- `GET /api/projects/{id}`: full project.
- `PATCH /api/projects/{id}`: `{title?,brief?,answers?,design?}`. `answers` and `design` merge. Any edit invalidates prepared packages and release approval.
- `POST /api/projects/{id}/dataset`: multipart field `file` (CSV up to 200 MB / 209715200 bytes); returns full project. Both browser upload views allow up to 30 minutes for transfer and profiling.
- `POST /api/projects/{id}/example`: `{name: "materials"|"leakage"|"noise"}` loads a synthetic example with a clear brief and dataset; returns full project.
- `POST /api/projects/{id}/analyze`: profile, check design, make split and run baseline on development data. Returns full project.
- `POST /api/projects/{id}/advise`: `{kind: "conversation"|"review"}` returns full project with an advice item; model errors are recorded as a visible notice with rules advice fallback. No CSV cell values are sent to model.
- `POST /api/projects/{id}/run`: start a bounded background onboarding run (scope, audit, development trial, review). Returns immediately. Poll `GET /api/projects/{id}` until `harness.status` is `complete` or `failed`. The server blocks concurrent writes during a run.
- `POST /api/projects/{id}/prepare`: `{acknowledge_review: true}` creates packages if hard checks pass; returns full project. Warnings remain visible. Acknowledge states this is a local reviewed prototype, not a secure production evaluation.
- `GET /api/projects/{id}/download/researcher`: ZIP, owner only.
- `GET /api/projects/{id}/download/organizer`: ZIP, owner only, includes held-out rows.
- `GET /api/projects/{id}/brief.md`: generated Markdown, owner only.
- `GET /api/projects/{id}/participant-link`: `{url: "/challenge/{token}"}` only after prepare.
- `GET /api/challenges/{token}`: participant-safe `{title,brief,metric,train_rows,download_url,limitations}`.
- `GET /api/challenges/{token}/download`: approved researcher ZIP only.

## Full project

```
{
 id, title, brief, created_at, updated_at, status,
 answers: {objective:"",prediction_unit:"",success_criterion:"",data_origin:"private"|"public"|"synthetic"|"unknown",labels_public:"yes"|"no"|"unknown",rights:"yes"|"unknown",compute_budget:"",token_budget:""},
 design: {target:"",task:"classification"|"regression",metric:"accuracy"|"balanced_accuracy"|"roc_auc"|"rmse"|"mae",split:"random"|"group"|"time",group_column:"",time_column:"",exclude_columns:[],test_fraction:0.2},
 dataset: null|{filename,rows,columns:[{name,dtype,missing,unique}],size_bytes},
 analysis: null|{checks:[{id,severity:"pass"|"warning"|"blocker",title,detail,action}],split:{train_rows,test_rows,strategy,group_overlap,duplicate_overlap},baseline:{status,metric,score,dummy_score,validation_rows,detail},summary:{blockers,warnings,passed},limitations:[]},
 checklist:[{id,label,status:"complete"|"attention"|"missing",detail}],
 advice:[{kind,mode,content,created_at}],
 prepared: false|{created_at,train_rows,test_rows},
 revision: number,
 harness:{status:"idle"|"running"|"complete"|"failed",stage,error?},
 events:[{stage,status,detail,at}],
 notices:[]
}
```

Answers use short plain text; non-empty fields are not proof of scientific validity. Design options are explicit controls. UI must allow draft saving and skip repeated questions. No APIs expose storage paths, secret seeds, test rows, or organizer data to participants.

## Dataset module contract

Owned by the dataset worker in `autokaggle/core/datasets.py`:

`profile_csv(path: Path) -> dict`: returns `rows, columns, size_bytes` and optional profile statistics; reject malformed/empty/oversized data with `ValueError`.

`analyze_dataset(path: Path, design: dict, answers: dict, seed: int) -> dict`: return `checks, split, baseline, summary, limitations`; use deterministic splits and no final-test model fitting/evaluation. Core should add findings for dataset design. API adds problem/rights/source/budget checks.

`write_partitions(path: Path, design: dict, seed: int, output_dir: Path) -> dict`: produce `train.csv` and `test.csv` with excluded columns removed (target retained); return counts and SHA256 hashes. Must use exactly same split as analysis. Do not include split seed in participant-facing output.

May add helper functions and tests under `autokaggle/tests/test_datasets.py`. Parent owns orchestration, persistence, exports, model, and API tests.
# Kaggle draft workflow additions

The organizer endpoints require an authorized email account, administrator owner session, or scoped review session. Cross-origin writes are rejected. Email addresses and login credentials are not part of participant artifacts.

| Method and path | Purpose |
| --- | --- |
| `GET/PATCH /api/projects/{id}/setup` | Read or save competition type, daily limit, explicit quota confirmation, and private organizer email. |
| `POST /api/projects/{id}/workflow` | Build a private draft and test supported data. Send a review invitation only if ready and configured. |
| `GET /api/projects/{id}/workflow` | Read checks, files, first development result, version, and email state. Changed inputs mark a draft stale. |
| `GET /api/projects/{id}/workflow/package` | Download the current researcher ZIP. Stale drafts return 409. |
| `GET /api/projects/{id}/workflow/preview` | Open the private website preview and development submission form. |
| `POST /api/projects/{id}/workflow/notify` | Explicitly send a new review link. Replace unused links and preserve active sessions. Automatic builds suppress duplicate invitations. |
| `POST /api/projects/{id}/workflow/submissions` | Organizer preview submission: `request_id` and `predictions_csv`. |
| `POST /api/projects/{id}/workflow/code-submissions` | Organizer code trial: `request_id` and `source_code`. Requires a verified Civo runner. |
| `POST /api/projects/{id}/workflow/access` | Create a submission-only preview token. Replaces the old token, preserves the daily allowance. |
| `POST /api/evaluation/{id}/submissions` | Same prediction contract using `Authorization: Bearer TOKEN`. No organizer access. |
| `POST /api/evaluation/{id}/code-submissions` | Same code contract using a submission-only bearer token. |
| `POST /api/review/exchange` | Redeem a single-use token for a seven-day session scoped to its project. Return a redirect to `/?project={id}&view=review`. |

Settings accept `competition_type: prediction|code`, `daily_submission_limit: 1..1000`, `submissions_confirmed: true|false`, and `organizer_email`. The default daily limit is 5, initially unconfirmed. Null fields are ignored. Unknown keys are rejected.

Development submissions return an aggregate metric rounded to six decimals, remaining allowance, and a safe status. Invalid prediction files count. An identical retry returns the previous result. A changed request with the same ID is rejected. Daily limits use UTC. The private preview has one team identity; public team enrollment is not delivered.

Workflow states are `not_built`, `draft`, `needs_changes`, `ready_for_review`, and `stale`. Check states are `pass`, `pending`, and `blocked`. Each check has a `blocking` flag. Organizer review requires all mandatory scientific details to be resolved or explicitly bypassed with a reason, plus passing technical checks. A reference baseline is optional. Review readiness does not approve publication. Notification states are `not_ready`, `not_configured`, `pending`, `sent`, and `failed`. Email acceptance by the configured mail provider is not proof of inbox delivery. The hosted service uses Gmail API sending over HTTPS. Live email-code receipt and sign-in passed in the sender Gmail inbox; other providers and actual review-invitation delivery were not checked in this run. See the email verification record (local operational record; not included in this repository).

Code submissions require a verified Civo runtime and execution controller. A change to the runtime controls or accepted worker code closes the execution gate. No route accepts arbitrary commands, pod specifications, container images, or private test downloads.

Code input is one UTF-8 Python file, at most 256 KiB. Prediction input is CSV, at most 5 MB. A disabled runner returns 503 before it reserves an attempt. Once execution starts, failures count toward the daily limit. Code results pass through the same trusted scorer as prediction uploads. Raw worker logs, hidden features, and answer values are not returned.

The data dialog uses the existing upload, PATCH, and analyze routes. Complete recorded question and task answers fill missing legacy audit fields. Manual edits, including explicit blanks, take priority. The bridge does not infer permission, label exposure, or dataset source.


## Organizer scope confirmation

`POST /api/projects/{id}/conversation/scope` accepts:

```json
{
  "field": "methodology",
  "summary": "Participants may choose any method that fits the fixed runner. External data are not allowed.",
  "resolutions": [
    {"requirement_id": "methods", "mode": "delegated", "detail": "Choose a method within the fixed runner and compute limits."},
    {"requirement_id": "resources", "mode": "confirmed", "detail": "External data and external services are not allowed."}
  ],
  "request_id": "unique-request-id"
}
```

Modes are `confirmed`, `delegated`, and `exception`. Confirmed decisions are organizer statements. Delegations assign supported implementation choices within fixed limits. Exceptions record accepted scientific uncertainty. Use `can_delegate` from the requirement record; scientific targets, metrics, permissions, and holdout decisions cannot be silently delegated. Use a nonempty summary and decision detail. Reusing a request ID must use the same payload.

To remove scope acceptance, send `field`, `request_id`, and `remove: true`. The response is the conversation view. Checklist items include `scope` and `can_accept_scope`. Question records include `requirement_id` and `why`. A `scope_checkpoint` reports the blocked criterion after two unsuccessful clarification attempts. Any proposed answer is unaccepted until the organizer confirms it.

Scope changes require rebuilt packages and review links. Validated organizer settings and technical checks cannot be resolved through this endpoint. Account ownership and the existing conversation write lock apply.
