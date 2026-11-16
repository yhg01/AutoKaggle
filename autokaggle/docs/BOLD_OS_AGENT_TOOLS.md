# BOLD OS agent tools

This change adds a bounded BOLD OS connection to the Lite interview agent. It uses the documented JSON API for the same read tools exposed through MCP. The model never receives the token. Evaluator jobs and participant packages receive no OS connection.

## Delivered scope

The current DeepSeek interview can call:

- `bold_read_rules`: read the current BOLDiquette.
- `bold_list_projects` and `bold_get_project`: find and check the owning project.
- `bold_list_skills` and `bold_get_skill`: discover and read current lab skills.
- `bold_list_tools`: inspect available OS capabilities.

The host loads `prompts/skills/bold-os/SKILL.md` when these tools are available. Project lookup proposes a choice; the researcher still accepts the contract. The model cannot call an arbitrary endpoint, send an OS write, execute skill files, or read an undiscovered project/skill ID. Requests use a fixed HTTPS origin, no redirects, bounded responses, a 20-second timeout, and at most six OS calls per interview turn. Errors omit credentials and upstream response text.

Only useful project metadata enters the interview. Tool results do not become imported source records or files in the research package. The agent must keep internal lab information out of participant artifacts. Record summaries can still enter the private conversation, so membership protection is required for every session reader.

## Activation

The connection is disabled by default. An operator must supply:

- `AUTOKAGGLE_BOLD_AGENT_ENABLED=1`
- `AUTOKAGGLE_BOLD_AGENT_TOKEN` in private server configuration, using a dedicated BOLD OS token.
- `AUTOKAGGLE_LITE_ACCESS_POLICY=members` and the approved `AUTOKAGGLE_LITE_MEMBERS` list.
- Private application access enabled. The trusted server sets the per-turn access marker; user messages cannot set it.

The temporary `verified_email` policy disables the OS tools even if a token is present. Do not change that policy to expose BOLD records to anyone with an email address. The planned Slack/BOLD identity connection can replace the explicit member list after its access tests pass. Do not switch an OS-enabled data store back to unrestricted email access.

This branch does not configure production credentials or change the current Civo access policy. The OpenRouter interview keeps its existing behavior; this first tool integration targets the currently deployed DeepSeek provider.

## Writes and Problem Bank

The model tools are read-only. The existing release outbox prepares validated registration records and performs bounded retries. A BOLD OS write must use an approved acting identity and follow the site's human-confirmation rules. A tool listed by the OS does not grant the model permission to execute it. Do not expose a general write proxy.

BOLD OS PR #31 is still under review. Problem Bank registration remains pending until that receiver is deployed and an approved connection is configured. This branch does not create OS proposals or alter the BOLDiquette. Its local skill describes the application binding; the OS remains the source for lab rules and lab skills.

## Verification

The focused test group passed 83 tests. Tests cover unknown actions, malformed arguments, undiscovered IDs, redirects, permission errors, oversized or invalid responses, credential filtering, call limits, deployment packaging, and denial under public email access.

A live read-only call used the existing OS JSON endpoint successfully. A separate live DeepSeek V4 Pro interview used synthetic OS fixtures, called project search and project validation, and returned a proposal for human review. No internal OS records were used in that model test. No write was made to BOLD OS. These are connector and model-loop tests, not proof of a deployed Slack identity integration.

## Prototype check — 16 November 2026

The member-only prototype was tested through its browser interface at `http://127.0.0.1:18883/lite`. It used an isolated database, live DeepSeek V4 Pro responses, and the live BOLD OS read API. The test account used the normal email-code routes with local mail capture. This did not test email delivery.

The first short interview request found the real AutoKaggle project, checked its record, showed its exact page link, and asked the researcher to confirm ownership. The agent did not treat the lookup as contract approval. The live tool trace also confirmed successful skills and tools discovery.

This test found a connector defect. The generic 24,000-character excerpt cut the live handbook before the Agentiquette section. Rules now include all accepted parts, up to a separate 128,000-character limit. Pending proposals are excluded. Invalid or larger rule documents return an explicit error instead of a partial policy. The follow-up live read returned all 78,164 characters, without truncation. The agent also fetched the live `bold-interview-coach` skill without truncation.

The focused regression group passed 90 tests. Seven new cases cover complete rule delivery, pending proposals, invalid rule data, and the size limit. Production access and BOLD OS writes remain outside this prototype test. PR #22 remains separate from the Civo release; BOLD OS PR #31 remains under review.

The researcher then confirmed the project in chat, opened **Review proposals**, and selected **Save defined details**. The saved project link, objective, title, and checklist count survived a browser reload. Required scientific gaps stayed open. The private source list remained empty: OS tool records were not added as imported participant sources.

Response speed remains a limitation. Project discovery took about 56 seconds end to end. The full-rules and interview-skill turn took about 97 seconds. OS reads each took less than one second; most time was in the model response. These are two measured turns, not a latency benchmark. The browser showed the working state and returned to an editable conversation after each turn.

A final browser turn asked whether this draft could be registered. The agent kept registration blocked, listed the missing release evidence, and did not claim an OS write. It also identified that `bold-interview-coach` concerns ML job interviews, so it did not apply that skill to the benchmark contract. All observed connector calls used the six read tools. The contract still contained only the three researcher-approved fields after this turn.
