# Internal data review

The internal interface presents saved records for human inspection. It does not
generate a diagnostic summary or decide whether a scientific statement is correct.
The project rail, record list and inspector keep the chosen project and original
source path visible. Search covers full record contents; filters and reverse order
operate within the selected category. Links and browser history preserve review
context. Copy and export contain the same redacted data returned by the API.

The workspace uses a compact two-row toolbar with category navigation in the
sidebar. Project metadata and snapshot controls open as popovers. At a measured
1423 × 706 viewport, the data panels receive approximately 570 px of height,
compared with 382 px in the earlier layout. The sidebar can collapse; a pointer-
and keyboard-operable divider resizes the record and detail panels. Double-click
resets the split. **Expand detail** gives the selected record the full workspace.
Long text scrolls with the containing panel rather than inside a small text box.

Visual presentation follows the data type: grouped field cards with individual
saved requirement-status cells, message and change timelines, measured token and
wall-time bars, and saved check panels. Detail tabs separate values and evidence,
requirements, provider inputs and outputs, metadata, links and original JSON.
The relationship panel counts records joined through saved source message IDs;
it makes no claim about unrecorded events. The List option keeps a compact scan
view available. Unknown numerical measurements are not plotted as zero bars.

## Record categories

Administrators have a compact **Problem Intake / Internal** switch in both
interfaces. Email accounts with administrator elevation keep their existing
identity. Ordinary accounts receive no Internal navigation. Switching back to
Problem Intake checks the existing project permission; inspecting another
owner's project internally does not grant interview access. In that case the
switch returns to the last permitted intake project or the user's workspace.
Only sanitized project/view URLs are remembered in tab session storage, never
record contents or credentials. Successful account changes clear these contexts.


| Category | Saved data |
| --- | --- |
| Conversation | Original messages, sequence, IDs, evidence links and linked calls |
| Model calls | Request input, instructions, provider output and returned reasoning; provider completion, application validation, trigger ID, usage, duration and capture limits |
| Saved fields | Field values, evidence quotes, requirement records, scope choices, bypasses, canonical organizer settings and evaluator configuration |
| Changes | Field history, scope and bypass audit records, response validation and repair records |
| Execution | Interview control state, harness state, dataset metadata, data analysis, workflow checks, saved events, development submissions and invitation metadata |
| Draft & artifacts | Saved README, model draft metadata, advice and workflow artifact metadata |
| Raw data | Expandable project record and review ledgers, including source metadata |

Relationships use saved message IDs. Older calls without a trigger ID remain
unlinked. A missing timestamp is not reconstructed from array position. Historical
before-state and current field state are labeled separately; current values are
not presented as historical after-state. No read endpoint calls migration or
conversation synchronization functions on a saved project.

Automatic checks run every five seconds while the page is visible. A changed
snapshot waits behind a **Load latest snapshot** button so the active selection,
expanded data and text being read remain stable. Manual refresh loads the latest
snapshot. No review data is persisted in browser storage.

## Identity and boundaries

The login page has one Sign in button. Email verification is always required;
checking Administrator access reveals an Access Key field. Both credentials are
validated in one request. Reauthenticating the same email preserves its workspace
and cached drafts. An invalid key leaves the email code unused. The eight-hour elevated cookie is bound to the
account owner. It cannot grant access without that email session or after an
account switch. An access key alone cannot sign in. Legacy shared administrator
cookies and their owner capability no longer grant workspace access. Existing
shared projects remain stored and can be inspected through Internal. Ordinary email and reviewer sessions have
no access to internal routes. Account elevation does not merge project ownership.

The snapshot includes canonical setup and workflow records, plus bounded
development-submission and invitation metadata ledgers. It excludes credentials,
owner capabilities, participant tokens, split seeds and test answer files.
Correspondence email addresses are redacted. Invitation token digests and grants
are not returned. This remains a read-only application boundary on the existing
host, not a private network endpoint.

## Capture limits

Each project retains the latest 30 model calls; each recorded text field is
capped at 24,000 characters. New request captures state their original redacted
length and truncation flag. Older captures retain the truncation marker. Truncated
JSON is shown as incomplete text, never interpreted as a complete request.
Reasoning is visible only when the provider returned readable text. Reasoning
tokens are included in output tokens and are not added a second time. Usage
totals cover retained measured calls only; no dollar cost is inferred.

## Local verification

`scripts/review_internal.py` can fetch redacted Civo snapshots through an existing
kubeconfig. `--live-model` runs a small synthetic interview with the worktree
source loaded into a separate Python process. It uses the existing OpenRouter
server configuration without copying keys, updating the deployment or writing
production projects. The project-root private `.env` was absent in this checkout.
No claim is made that a local key file supplied this validation.

The latest live validation (31 October 2026, 18:43 UTC) used `openai/gpt-6.1-sol`:
one completed provider call and an accepted application validation, with exact
trigger linkage, 12,029 input tokens, 857 output tokens (142 reasoning tokens),
and 10,589 ms duration. The receipt and
redacted snapshot are saved under ignored `autokaggle/test-results/internal-review`.
`--reuse-snapshot --serve` starts a loopback-only preview with a separate local
test credential. Its preview-login route exists only in the QA server, not the
deployed application. Existing production accounts and deployment are unchanged.
