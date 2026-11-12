# Lite administrator log repair

## Cause

The shared admin console read Full's conversation and model-call fields. Lite stores its messages, interview turn count, contract, and build records elsewhere. The affected LOB-Bench session had 27 saved messages and 10 interview turns, but the old list showed `draft · 0 calls`.

Lite did not save provider request/response traces before this repair. Those old traces cannot be reconstructed from the saved messages. Civo also collected evaluator worker logs only after a job ended.

## Change

- Read Lite messages, accepted contracts, pending proposals, contract history, packages, source records, evaluator builds, and submitted results in the admin console.
- Label interview turns separately from recorded model requests. Show the historical logging gap explicitly.
- Record new interview requests and responses, tool calls, errors, schema-validation status, token use, and elapsed time. Record before sending, so a server restart marks an unfinished request as interrupted.
- Retain the latest 30 requests, with a 24,000-character limit per text field. Mark truncation. Redact credentials and email addresses. Do not save hidden model reasoning.
- Add administrator-only build log reads with a 256 KiB tail limit. Reject missing builds, arbitrary file names, symlinks, and non-file targets.
- Save bounded Civo log snapshots about every ten seconds while a build runs. A failed log read does not stop the build or remove the previous snapshot. The admin clicks the log button again to refresh it.
- Keep diagnostic records outside the interview input state. Preserve the scientific contract and package version calculation.
- Recheck apparent worker interruptions against the saved state under the project lock. A worker that finishes during a page refresh must not be reported as failed. Normal polling remains available during publication.

## Verification

- 208 Python regression checks passed; one optional Docker check was skipped. After the final validation-record change, 20 focused Python checks passed. These sets overlap.
- All 278 JavaScript checks passed after PR #18 was included. JavaScript syntax and Git whitespace checks passed.
- Browser checks used the local admin interface with a read-only copy of the affected session and a completed acceptance build. Verified messages, correct turn count, contract fields, agent logs, test logs, and new model inputs and outputs.
- A live DeepSeek V4 Pro interview through the browser completed in 81.53 seconds. The saved trace recorded 5,136 input tokens and 7,952 output tokens. The latter includes 6,370 reasoning tokens. The reasoning text was not saved.
- The new log collector was exercised against an active Civo worker without changing or restarting the job. This was a read-only collection check in a separate process.
- Production administrator authorization and ordinary-account denial are covered by backend checks. The local presentation fixture used a local-only administrator override. It does not establish a production browser sign-in test.

## PR review

The combined Python run found two defects. Diagnostics changed the input state during schema repair. A concurrent build completion could also make a stale page read appear interrupted. Both defects have focused regression coverage.

PR #18 limits repository import detection to GitHub repository root URLs. A file URL was sent through the local chat with a real DeepSeek V4 Pro response. The response was saved and validated, and no repository import started. This request took 32.53 seconds.

The review also found a separate generated-evaluator gap. The existing acceptance checks verify primary fitness, example ordering, invalid input, dependencies, and release integrity. They do not systematically test every secondary output or reference-data field described in the scientific contract. A generated release omitted required diagnostics and reference identity despite passing its fixture checks. This remains follow-up work; passed release checks must not be described as full scientific validation. Private incident details remain outside Git.

## Deployment

The previous Civo evaluator build finished and published successfully. Deploy only while all current jobs are idle. Record the final release and live checks here after deployment.
