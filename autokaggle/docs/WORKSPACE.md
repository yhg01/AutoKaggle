# Research sessions, warm starts, and data controls

This change adds session tools to the existing chat. Open **Sessions** in the header. The tools use dialogs with internal scrolling. The interview remains the main page.

## Start from a paper and repository

Accept the data-storage notice and supply the organizer email. Open **Sessions → Start from research**. Enter a public HTTPS paper PDF or abstract link, a public GitHub repository root link, or both. Imports run in the background. The dialog reports the current stage and offers retry after a failure. A restart marks interrupted work for an explicit retry; it does not lose the interview.

The importer reads public text, freezes the repository commit, and reads selected README, license, environment, and starter files. It does not install dependencies, execute imported code, retrieve repository datasets, or reproduce reported results. GitHub rate limits and source access errors remain visible.

The agent proposes a short starting brief and up to four open decisions. Edit the brief, then select **Use this starting brief**. That explicit approval creates a researcher message. Imported text alone cannot establish challenge readiness, dataset permission, private answers, or completed experiments. The model is instructed to treat external text as reference material and to ignore instructions inside it.

An approved reference carries its paper hash and repository commit into the research ZIP through references.json and WARMSTART.md. These files explain how a research agent can prepare existing reference code within the method, license, dependency, and offline-execution rules. Source code and its environment are not silently bundled or executed. Dataset import from Google Drive remains separate planned work.

Import bounds:

- HTTPS only, port 443, no URL credentials. DNS destinations must all be public. Connections use the checked IP with normal TLS hostname verification. Every redirect is checked again. Environment proxy settings do not route these requests.
- A fetch has a socket timeout and a 30-second connection deadline. At most five redirects are followed.
- A paper download is at most 16 MiB. PDF extraction uses a separate process, a time limit, at most 30 pages, and at most 40,000 text characters. The Linux process also has a 512 MiB address-space limit. Scanned or encrypted PDFs require another readable source.
- At most eight selected repository files are read from one immutable commit. Each file is at most 200,000 bytes; its stored model excerpt is at most 7,000 characters. Truncation is recorded.
- One import runs per session. Repeating the same import request ID returns its existing job. Explicit retry uses a new ID. Model calls still reserve and consume the existing interview call budget.

## Ask the agent to look something up

Select **Attach** in the chat, or drag files onto the conversation, to give the agent papers, notes, code, or logs. PDF, Word, PowerPoint, Excel, OpenDocument, RTF, HTML, and notebook files are read, as are ZIP and gzip archives and any file that reads as text, whatever its extension. Scanned PDFs, images, and legacy Office files are refused with the reason. A document can be up to 50 MB, and a session can hold 20. Files wait inside the message box until you send. They then appear above your message, and a message can contain only files. Removing that message returns its files to the message box.

Only the extracted text is kept, up to 400,000 characters. Documents give context for the interview. They never become the challenge dataset and they do not enter the website, the research ZIP, or the private package. A dataset still comes through **Data & checks**. Remove a document from its card in the message box or above your message, or delete the session to remove them all.

The agent reads nothing on its own. Ask for what you need in the chat, for example to find a method in an attached paper or to confirm a unit in a linked table. On request it can:

- read an attached document or a link you sent, including a PDF link;
- answer fixed questions about the uploaded dataset, such as column ranges, whether columns identify a row, and row counts;
- search the public web, when you ask for a search, and read the pages that the search returned.

It can open only links you sent, links from your imported sources, and links a search returned. A link written inside a document or a page is not opened. Each message allows six lookups, and they count as one model call. Text it reads, dataset summaries, and search queries are sent to the configured model service. Page text and search results are untrusted, and the agent does not follow instructions in them.

While the agent works, each operation appears one at a time, and the current one pulses: reviewing your message, each lookup, and reviewing the results. It then reports what it found and where, in a reply above its next question. The list collapses into **steps** on that reply. Opening it shows the same operations, including failed attempts. Model reasoning is not shown. A lookup records nothing. When a finding answers a requirement, the agent shows the exact value and its source and asks you to confirm it. The value is recorded only if you accept it. A question or a lookup request does not count as an unsuccessful answer to the open question.

## Resume, share, and revise

**Sessions** lists accessible sessions with title, update time, and ownership. Open an existing session to resume it, or create another session. Session access is checked on the server. An arbitrary project URL does not grant access.

The owner opens **Share → Create handoff code**. Share the code privately with a collaborator. They sign in with their own email, open Sessions, accept the storage and collaboration notice, and enter the code. It works once within 24 hours. A new code replaces an unused earlier code. Only a digest is stored.

Joining adds edit access to this session. It does not replace the owner or grant another session, account, or Internal access. The owner retains session/dataset deletion and membership control. Collaborators can leave. Revocation blocks later API access and revokes existing submission tokens. It cannot recall already downloaded or visible copies. New human turns have an organizer or stable collaborator label, without publishing an email or account capability. Session writes use the existing project lock; concurrent actions receive a recoverable 409.

**Attempts & changes** lists up to twenty saved development attempts. Select **Revisit the problem definition** after a working draft exists. The revision keeps previous context and includes up to ten measured attempt results and their versions. It asks what should change. It does not expose final scores. A scientific change requires rebuilt artifacts. The existing daily allowance continues across revisions.

## Researcher names

Email sign-in asks for a name when the verified account has no name yet. Saving it returns to the requested challenge. Returning accounts use the saved name. A researcher can edit it through **Sessions → Profile**. An existing signed-in account can continue its current session; name collection is presented on its next email sign-in.

Names appear in private session lists, shared-session member lists, new message author labels, and Internal review. Administrators can search projects by researcher name across all pages. **Project details → Researcher name** updates the name on the verified account that owns that project. This also updates its other session listings. This supports labeling existing accounts without asking the researcher to restart their work.

Names are display labels. Duplicate names are allowed. Stable account IDs, verified email sessions, project ownership, and collaboration grants determine access. Existing accounts and data are preserved by an additive `researcher_profiles` table. Name changes update account metadata without rebuilding research packages. Old message author labels stay as recorded; new turns use the current name and role. Legacy messages and non-email review grants keep their existing role labels.

The profile form explains who can see the name. Account profile data are separate from session content. Session deletion keeps the sign-in account and its name; account-level erasure requires the operator. Profile names are not added as account metadata to model requests or participant packages. A name that a researcher writes in the scientific conversation is processed as conversation content.

## Edit or remove an earlier answer

Select **Edit or remove answer** beside a researcher turn. Write a replacement, or choose removal. Confirm the operation explicitly.

The selected old turn is removed from the live record. A replacement is recorded as a new researcher turn. The server removes generated messages, model traces, old revision snapshots, artifact files, results, and access grants that could retain withdrawn text. It removes dependent checklist evidence and reopens affected decisions. Independent requirements and scope decisions stay recorded. Other researcher messages remain available for reassessment. Reference material supplied independently can remain; use Data & privacy to remove imported reference files as well.

The agent rechecks remaining evidence with one normal bounded interview action. An uncertain retry keeps the same operation ID and cannot create another replacement or model call. Original request IDs for an erased turn cannot reintroduce its text. If reassessment fails, erasure has already been saved; the failed model call cannot restore deleted content. The remaining message can be retried through the existing recovery path.

Results erased during content removal no longer appear in attempt history. Non-content daily usage counts remain, so removal cannot reset the five-submission allowance. Ordinary revision retains attempt history.

## Compute estimates

Budget notation is free text. Examples include A100 x8 x24h, GPU-hours, CPU time, token counts, API-call counts, dollars, an existing allocation, or no model calls. The agent must preserve the supplied units and must not invent a price or currency conversion. Unknown still leaves the requirement open.

Evidence-backed compute and token choices synchronize into their corresponding answer fields while preserving explicit manual overrides. Challenge records contain compute_estimate and token_estimate. The older compute_usd and tokens_usd fields are populated only when dollar notation was actually supplied. Estimates do not change the fixed code-runner resource limits. The interviewer must record a runtime mismatch rather than claim unsupported hardware is available.

## Storage acceptance and erasure

The storage notice is available at /privacy and in **Data & privacy**. It explains local versus hosted storage, model processing, sharing, deletion, and backup limits. Research writes require explicit acceptance of the current notice. Consent records include the policy version, time, and a hashed actor identifier. Existing sessions need acceptance before further research writes. The deployed configuration explicitly enables this gate. Only legacy automated fixtures disable it; dedicated tests use the production default.

The owner can delete an attached dataset or the complete session. Dataset deletion removes the file and generated artifacts/results. Session deletion removes the project, files, model records, ledgers, memberships, invitations, and submission/handoff capabilities. Content is removed from live storage, not merely hidden from the interface. A pending download cannot recreate a deleted project. SQLite secure-delete and WAL checkpointing reduce retained database-page copies.

Email sign-in records are separate from a research session. Deleting a session does not delete the sign-in account or recall email/downloads held by recipients. Contact the service operator for account-level erasure or copies outside the live application. These controls do not by themselves establish complete GDPR compliance.

### Backup operation

A private erasure-journal.json in the data root records only the affected project ID, erasure time, and scope. It is written atomically before content removal. Keep the latest journal independently of database snapshots. Never replace it with an older backup during restoration.

Store startup applies this journal before serving restored data. Whole-session tombstones remove restored projects. For content erasure, a snapshot older than the erasure is removed as a whole rather than reconstructing withdrawn content. A newer, already-cleaned project can remain. This intentionally prefers erasure over restoring an older partial conversation.

The operator must restrict backup access, set and enforce a retention period, and remove expired backups. Copy the latest journal with disaster-recovery materials. Restore only with code that enforces the journal. Startup filtering does not physically edit every historical backup, so the operator must keep those copies outside normal use until disposal. See the ICO guidance on [erasure and backups](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/) and [storage limitation](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/storage-limitation/).

## API additions

All project endpoints require the existing owner, collaborator, or scoped review authorization. Permanent deletion and access management require the owner where stated.

| Method and path | Purpose |
| --- | --- |
| GET /api/projects | List accessible sessions, role, and deletion permission |
| GET /api/projects/{id}/privacy | Current notice and acceptance status |
| PATCH /api/projects/{id}/privacy | Accept with accepted: true and the current version |
| DELETE /api/projects/{id} | Owner deletes the session; confirm: true required |
| DELETE /api/projects/{id}/dataset | Owner deletes dataset and derivatives; confirm: true required |
| GET, POST /api/projects/{id}/sources | Inspect or start a background import; POST supplies links and request_id |
| POST /api/projects/{id}/sources/apply | Approve edited brief with brief and request_id |
| DELETE /api/projects/{id}/sources | Remove imported reference records and related model traces |
| POST /api/projects/{id}/conversation/messages/{message}/forget | Remove or replace an answer with request_id, confirm: true, and optional replacement |
| GET /api/projects/{id}/attempts | Development attempt summaries |
| POST /api/projects/{id}/iterate | Start or resume revision with request_id |
| GET, POST /api/projects/{id}/handoff | List collaborators or issue an owner-controlled code |
| POST /api/handoffs/redeem | Join with code and accepted: true; ordinary account access is required |
| DELETE /api/projects/{id}/handoff/{member} | Owner revokes a collaborator; a collaborator can remove their own membership |
| DELETE /api/projects/{id}/handoff/codes | Owner revokes unused codes |

An empty session can be created before consent so the interface can present the notice. A research brief requires storage_accepted: true on creation or acceptance before a later write. A blocked research write returns 428. The normal API and offline test harnesses can use these endpoints without browser-only flags.

## Verification

Run the Python and Node suites plus affected live OpenRouter checks. The workspace verification script exercises real paper/repository downloads, model-generated proposals, approved interview text, hardware/token notation, collaborator access, answer replacement, idempotent recovery, and erasure. The iteration verification script seeds explicit synthetic scientific decisions, writes a live draft, builds the package, scores an actual prediction file, and makes a targeted live revision. The seeded definition is not evidence that the interview completed every requirement.

    python -m pytest autokaggle/tests -q
    node --test autokaggle/tests/*.cjs
    python -m autokaggle.scripts.live_workspace_verify
    python -m autokaggle.scripts.live_iteration_verify

Scripts read the private OpenRouter key from the root .env and use temporary project stores. Reports belong under ignored test-results. No email is sent by these verification scripts. UI work also needs live browser checks of consent, import/retry, session switching, edit/removal confirmation, attempt review, and small-screen layout.
