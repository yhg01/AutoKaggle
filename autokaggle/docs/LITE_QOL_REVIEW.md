# Lite interview and evaluator review — 16 November 2026

Most of Kaito's reported difficulties are system defects. They concern the interview, contract coverage, test quality, and asset handling. Using the pinned scorer through an adapter is the intended design. Lack of access to the research cluster or licensed data is an external constraint.

## Evidence and responsibility

A read-only inspection of Civo found that Kaito's saved release finished on 12 November at 18:11 UTC. It predates the merged contract-coverage and OFI fixes. Updating the application does not rebuild an existing evaluator repository. We did not change his live session or repository during this review. We have not inspected the later changes made outside Lite by his other coding agent.

| Reported point | Assessment | Required action |
| --- | --- | --- |
| Repeated questions, future release URL, incorrect attribution | System defects. The saved conversation contains the circular release-URL request. The prompt also described an older manifest and result interface. | Teach stage responsibilities and current interfaces. Retain evidence for unchanged decisions. Review only changes by default. Implemented in this branch. |
| A GitHub link sent a reply to import | System defect. PR #18 fixed links inside repositories. Repository-root and paper links still triggered import. | Keep normal replies as messages. Offer explicit source reading. Implemented in this branch. |
| Missing secondary metrics, saved outputs, reference identity, and structural checks | A release defect when the accepted contract requires them. | PRs #19 and #21 added coverage and review checks. A new build is needed to apply these checks to the old evaluator. |
| Thin synthetic data and a copied-reference fixture | Test-design defect if these are the only positive tests. A copied-reference oracle can still be a useful sanity check. | The existing quality plan requires meaningful fixtures and coverage. Use realistic, perturbed samples and invalid inputs. Research-data validation remains separate. |
| Licensed data and large artifacts needed workarounds | A platform mismatch in the older implementation. Researchers must still supply permitted assets and resource bounds. | Existing support includes local reference data, file or directory artifacts, and bounded processing. The interview now explains this support. |
| The output wrapped the official scorer rather than rewriting it | Intended design. Reuse reduces the risk of changing the scientific metric. | Retain the pinned scorer. Test the adapter, data selection, diagnostics, and recorded outputs. |
| Isambard or research assets were unavailable | External constraint. This does not justify claiming research validation. | Build and test software with synthetic fixtures. Keep the research-data stage pending until the assets and execution resources are available. |

Earlier work: [PR #18](https://github.com/yhg01/AutoKaggle/pull/18), [PR #19](https://github.com/yhg01/AutoKaggle/pull/19), [PR #21](https://github.com/yhg01/AutoKaggle/pull/21), and the [LOB-Bench quality review](LOB_BENCH_QUALITY_REVIEW.md).

## Improvements implemented

1. Both model providers receive stage responsibilities, accepted evidence, proposed evidence, and the current package interface. The researcher defines the science. The coding agent writes and tests the adapter. The service creates the future release identifiers.
2. The prompt retains required secondary metrics, saved outputs, reference identity, and structural checks. It accepts licensed local data and distinguishes software checks from research-data validation. It directs software feedback to evaluator review.
3. Unchanged accepted facts keep their evidence in later proposals. Line-wrap and whitespace differences can recover an exact source excerpt. Paraphrases, changed numbers, and new unsupported values remain suggestions. Exact attribution does not prove that every claim follows from the excerpt; human review remains required.
4. Normal Send always sends a reply after the opening interview. A paper or repository link offers **Read linked sources**. This opens a review of the selected links and preserves the complete reply. Cancel and failed imports keep the draft. The initial paper/repository interview and code-review routing remain separate.
5. Revision review shows added, changed, and removed fields first. Unchanged accepted fields are folded away. An already accepted suggestion is labelled as accepted. A complete proposal shows **Next step**, rather than implying an unresolved decision.
6. An older release without coverage evidence gets an upgrade notice. The notice explains that a new build is required. A current checked release does not get this notice merely because its history contains an older release.

The interview changes do not edit `lite.py` or the packaged runner. Their file hashes remain unchanged, so this branch does not invalidate existing contracts merely by changing interview behavior.

## Validation and limits

- 165 Python tests passed across interview, evidence, task types, project links, evaluator builds, coverage, and release checks. One optional Docker runtime test was skipped. Targeted provider and release-history checks were repeated after the final changes.
- 63 JavaScript tests passed. These cover ordinary links, explicit import, cancellation, failed-import retries, opening questions, code review, revision differences, and legacy-release notices.
- Four live DeepSeek V4 Pro turns passed across generation, environment, and optimization scenarios. OpenRouter was not used, under the owner's temporary provider instruction.
- The generation test used a local copy of Kaito's saved conversation. Two short replies went through the browser. The agent retained the local-data and secondary-metric requirements, asked for the missing project link, and recorded the approved four-OFI exception as a researcher decision.
- Through the browser, we accepted the revision, prepared its package, downloaded the ZIP and config, and refreshed the session. Review showed two changed fields and 24 unchanged fields. The ZIP contained 13 files. The downloaded contract matched the ZIP contract. The OFI exception retained researcher evidence. Its one fixed evaluation seed was `560596405` for test contract `c305652ae31d98b67d2f3994`.
- The environment check changed the episode count to five without changing the agreed fixed horizon. The optimization check retained custom fitness and proposed a correction to inconsistent old task wording.

These tests cover the changed interview and review workflow. This branch did not generate a new LOB-Bench evaluator, run licensed research data, send review email, create a BOLD repository, or register a test project in BOLD OS. The local project link used in the browser test is a test identifier. It was not checked against BOLD OS. Civo was inspected without modification. No deployment is included.

Private test records and the browser screenshot are under ignored `autokaggle/test-results/lite-qol/` in the task worktree. They are not part of Git.
