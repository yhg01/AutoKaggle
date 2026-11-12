# Public-data research

Private-answer evaluation remains the default. Public training data can use that setting. The answer-exposure check refers to evaluation answers, not the training-data source.

For a prediction task with known public answers, open **Data & checks**. Select **Yes** for answer exposure and **Public-data research** for the evaluation setting. Save and run the checks. Build the workflow from **Draft & package**. The older separate researcher/organizer export does not support this setting.

This option changes only the public-answer gate to a disclosed warning. Unknown exposure remains blocked. Data permission, source, scientific definition, split, scorer, contact, and submission checks still apply. Environment and code competitions retain their existing paths.

## Participant steps

1. Download the research ZIP. Read its exposure notice and AGENTS.md access rules.
2. Develop locally using the approved training data. Save the predictions and the exact source used to produce them.
3. Edit `reproduction.json`. Record the entry point, command, environment, seeds, challenge version, model assets, resources, and prior answer access. Replace the example disclosure.
4. Create a ZIP containing this manifest and the required source files. For the supplied baseline: `python -m zipfile -c code.zip baseline.py reproduction.json`.
5. Upload the prediction CSV and code ZIP together. Or run `python submit.py --url SUBMISSION_URL --predictions predictions.csv --reproduction-code code.zip` with the submission-only token in `AUTOKAGGLE_SUBMISSION_TOKEN`.

Code ZIP limits are 512 KiB compressed, 96 KiB of UTF-8 text, and 32 files. Relative paths are required. Links, encrypted archives, binary files, and archive formats other than stored or deflated ZIP are rejected. Include immutable references and hashes for larger model assets. The service does not retrieve those assets. Keep credentials out of the ZIP.

The service saves both files with hashes and a challenge version. Retries with the same request ID and identical files return the saved result. Changing either file requires a new request ID. Missing or malformed code packages fail before an attempt is reserved. Invalid predictions count toward the daily allowance. The existing five-per-day default remains in effect.

## Review and result

The prediction format is checked first. A separate model then reviews the submitted text for answer lookup, embedded answers, prohibited access, scorer probing, and attempts to control the review. It receives only submitted text and selected public contract fields. It has no tools, dataset rows, predictions, test answers, or scorer credentials. Submitted code is never executed by the web process.

- **Clear:** Show a provisional development score. This means no concrete concern was found in the source review.
- **Flagged:** Withhold the score. Show the source excerpts and reasons. Submit a corrected attempt with a new request ID.
- **Review pending:** Withhold the score. Retry from the submission result or **Attempts & changes**. Up to three review calls are allowed for the saved attempt. Review retries do not use another submission.

The organizer can inspect reports and download saved code and predictions. Submission tokens cannot read those artifacts. Existing project ownership, deletion, and erasure controls apply. Changes to the challenge invalidate submission tokens and prevent review retries against the old version.

## Limits

Source review does not execute the attempt or verify reproduction. The result explicitly records reproduction as `not_run`. No automatic reproduction worker is added in this release. Multi-file dependencies and binary assets need a separately controlled execution path before we can report a verified reproduction.

Local participants can access their own machines. Instructions in AGENTS.md cannot enforce network restrictions there. The service does not claim that local research ran offline. Prior model knowledge or earlier access can still affect results. The exposure notice remains after a clear review. Public research scores must not be presented as blind results or as proof of a scientific discovery.

This explicit practice setting and its per-attempt code review differ from the default private-answer workflow. Existing private prediction submissions continue to accept a CSV without a code ZIP or this review.
