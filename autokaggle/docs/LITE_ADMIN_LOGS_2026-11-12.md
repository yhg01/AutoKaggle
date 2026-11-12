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
- Preserve the scientific contract and package version calculation. No changes to the contract generator or participant runner.

## Verification

- 208 Python regression checks passed; one optional Docker check was skipped. After the final validation-record change, 20 focused Python checks passed. These sets overlap.
- 55 JavaScript checks passed. JavaScript syntax and Git whitespace checks passed.
- Browser checks used the local admin interface with a read-only copy of the affected session and a completed acceptance build. Verified messages, correct turn count, contract fields, agent logs, test logs, and new model inputs and outputs.
- A live DeepSeek V4 Pro interview through the browser completed in 81.53 seconds. The saved trace recorded 5,136 input tokens and 7,952 output tokens. The latter includes 6,370 reasoning tokens. The reasoning text was not saved.
- The new log collector was exercised against an active Civo worker without changing or restarting the job. This was a read-only collection check in a separate process.
- Production administrator authorization and ordinary-account denial are covered by backend checks. The local presentation fixture used a local-only administrator override. It does not establish a production browser sign-in test.

## Deployment

Pending the existing Civo evaluator build. The release must wait for active jobs to finish. Record the final release and live checks here after deployment.
