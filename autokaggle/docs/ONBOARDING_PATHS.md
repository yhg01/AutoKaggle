# Internal, Speedrun, and Full

The owner approved these three paths on 9 November 2026. There are two trust modes. Speedrun is an entry path within Full.

| Path | Intended use | Evaluation contract |
| --- | --- | --- |
| Internal (Lite) | Trusted lab research on established ML tasks. | Visible fixed seeds and researcher-run results. The service checks submitted evidence; it does not establish independent reproduction. |
| Speedrun | A Full challenge based on a paper and public repository. | The same Full data, scorer, submission, access, and execution gates as a challenge started from scratch. |
| Full from scratch | A new research problem defined through an interview. | The Full competition contract and its applicable scientific and technical checks. |

## Access

[Internal on Civo](https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite) has a separate service, administrator credential, database, and persistent volume. Sign in with an approved lab email. A verified email alone does not grant membership. A shared project still requires lab membership and project access. See [Internal deployment](../deploy/LITE_WEB.md).

[Full on Civo](https://ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/) retains its existing service. This worktree implements Speedrun; implementation and tests do not imply that Full's live deployment has been updated. Check the release record before directing users to the new entry control.

Vercel is not used. The owner corrected that initial request to Civo.

## Full entry and source review

1. Sign in, provide the organizer contact if needed, and accept the storage notice.
2. Choose **Start from a paper and repository** or **Start from scratch**. Saved interviews resume directly.
3. For Speedrun, supply a public paper or source page URL, or upload a text PDF up to 16 MiB. Add the corresponding public GitHub repository. One source can start the process, but missing material remains open.
4. Review the editable proposed brief and unresolved questions. Imported text is reference material until this review. Approval sends the text through the normal Full interview and its evidence checks.
5. Answer targeted follow-ups. The agent must not infer data permission, private-answer status, actual reproduction, or compute authorization from a publication.
6. Use the existing draft, package, submission test, and organizer revision flow. An imported brief cannot bypass a missing evaluator or other technical gate.

Repository imports use a frozen commit and bounded text. Imported code is never executed during source preparation. PDF parsing runs in a bounded subprocess. Source proposals allow up to 6,000 characters so supported protocol details can survive review. Published facts and unresolved organizer choices remain distinct.

The project stores `scratch` or `speedrun` as entry metadata. This field changes neither trust mode nor evaluator configuration. Selecting a different entry does not clear recorded messages or make a package ready.

## Verification record

On 9 November, the integrated worktree passed 1,347 Python tests and 250 JavaScript checks. Tests cover source review and PDF bounds, saved-session routing, consent and ownership, private-answer protection, scorer failures, disabled code runners, and unchanged evaluation versions. Eighteen source tests passed again after preserving the existing URL-import retry fingerprint.

Live OpenRouter checks used `openai/gpt-6.1-sol` with medium reasoning. Full source import, explicit brief approval, checklist extraction, and a normal short opening message passed. The FreeSolv case retained the public-answer concern and did not become ready automatically. An imported reference is not necessarily a complete competition protocol.

Internal checks used public ESOL and FreeSolv records. Each passed source review, ZIP/config consistency, stable seeds on rebuild, a small local control run, result logging, duplicate-result handling, and missing-seed rejection. These were engineering tests on 96 molecules per case. They did not train a model or reproduce a published scientific score.

Local evidence is under the ignored `autokaggle/test-results/three-paths-2026-11-09/` directory. Private deployment receipts and credentials remain outside versioned files. Browser testing was blocked by the browser tool's saved site permission at the time of this record; automated UI checks are not a visual test.

## Integrated preview update

The separate Civo Speedrun preview preserves the live public-data safeguards and passed 1,374 Python and 252 JavaScript checks. Full production was not replaced. See [the overnight review](OVERNIGHT_REVIEW_2026-11-09.md) for deployment, the separate quant branch, and the blocked browser runs.
