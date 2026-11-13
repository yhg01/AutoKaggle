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
