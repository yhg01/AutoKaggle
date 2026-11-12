# Automatic evaluator publication — 12 November 2026

Lite now publishes a tested evaluator to its problem's private GitHub repository after the acceptance checks pass. The researcher does not need a separate publish action. Each problem keeps one repository. Later tested releases add version tags.

## Changes

- Added the `AUTOKAGGLE_LITE_AUTO_PUBLISH` service setting. It is enabled on Civo Lite with owner `bold-lab-ai` and the approved token from private configuration.
- Recorded publication progress, attempts, failures, repository, release tag, and exact commit. A failed publication retains the tested evaluator and has a retry action. Retrying reuses the saved repository.
- Held the project lock during publication. A contract edit, deletion, duplicate publication, or new build cannot race the push. A changed contract cannot publish an older release as current.
- Required both the local release tag and `main` to match the tested commit. Pushes do not overwrite external commits or changed tags.
- Added a repository link and a GitHub ZIP download pinned to the tested commit. New ZIP releases record their revision through Git archive metadata. The runner checks release file digests before scoring.
- Preserved the build and publish control states while the interface refreshes. Build controls remain disabled during a build or publication.

The GitHub token stays in the trusted web service. The model and build job receive no GitHub credential. Existing accepted sessions are not published in bulk when this setting is enabled.

## Checks

The focused Python suite covered evaluator builds, publication, the Lite workflow, and email access: 107 passed and one optional Docker test skipped. One expected-file-list assertion needed an update for the two archive metadata files; its rerun passed. The archive test also passed. All 46 Lite JavaScript tests passed.

Regression checks covered automatic publication, one repository across multiple versions, failed builds, failed pushes, retries, concurrent edits, changed contracts, restart recovery, secret-safe errors, immutable tags, downloaded archives, and rejection of modified release files.

The local browser test used two short research replies and real DeepSeek V4 Pro responses. It accepted the contract, prepared the package, and started the evaluator build. The coding agent made 13 model requests. All ten fresh-clone checks passed. The interface then displayed the private repository and download link without a publish click:

- Repository: https://github.com/yhg01/lite-eval-automatic-publication-acceptance-76090831
- Release: `v1`, commit `668461ca34b08f1fcbb835d8952460c3cfdcb978`
- Downloaded GitHub ZIP: 24,028 bytes. The extracted evaluator returned fitness 16 for `x=7` over three seeds. A boolean candidate was rejected. The recorded revision matched GitHub.

## Deployment

Implementation commit: `b6999df`, on `codex/agent-led-task-workflows`, in [PR 17](https://github.com/yhg01/AutoKaggle/pull/17).

Lite source digest: `70f0b34c50cbee54bd31c242b727d441ed5b00ad7e75ca6fd5c9222596ff69a1`.

Private backup before rollout: `/data/projects/backup-20261112-151457.sqlite3`. All ten existing Lite project bodies were unchanged after deployment. Both services had one available replica. Full retained source `c909b1150ecd43a9511408c2f60b2003400a8bb706d991d5e056e694bb6177ad`.

The Lite service retained its temporary verified-email access policy and Kubernetes build runtime. The deployer preserves those settings on later updates.

## Limits

The Civo check uses the application API and its real Kubernetes build jobs. Browser access to the Civo Lite origin was previously blocked by the browser permission policy; it was not bypassed. The local interface was tested through the browser.

Private repository downloads require GitHub access. Lite does not add collaborators automatically. An interrupted publication needs a retry request; it does not restart automatically. These tests validate publication and scoring plumbing on a small synthetic problem. They do not establish scientific validity for an arbitrary generated evaluator. BOLD OS problem-bank synchronization remains separate work.


## Initial Civo BOLD connection check (resolved later)

Civo completed the live evaluator build with DeepSeek V4 Pro: 12 model requests, 91.0 seconds in the Kubernetes build job, and all ten acceptance checks passed. The tested commit is `fd734263e9a3e08c706987f08c2f1d8958d25937`. The saved session is `2c413be2-75eb-448f-acea-9232d4459552`.

Automatic publication then reached GitHub and received HTTP 403: `Resource not accessible by personal access token`. A direct retry of `POST /orgs/bold-lab-ai/repos` with the same private token also returned 403. No BOLD repository was created. The ready local release remains available and its publication status is failed, with a retry action.

GitHub returned `administration=write; repository_creation=write` in its accepted-permissions header. Its [repository creation documentation](https://docs.github.com/en/rest/repos/repos#create-an-organization-repository) permits either Administration write or Repository creation write. The token must cover the target organization and new repositories, and Contents write is needed for the push. The user has been asked to check the approved token's scope and permissions. We have not substituted a broader personal credential on Civo.

The supplied credential can authenticate and read BOLD repository metadata. That check alone did not establish creation access. BOLD end-to-end publication remains blocked by this GitHub refusal. After access is corrected, retry the saved evaluator's publication; no model build is needed.

Civo health returned HTTP 200. Anonymous entry redirected to email login, and anonymous access to the test evaluator returned 404. The temporary operator test session was removed at the end of the test.

## Permission retry succeeded

After the owner updated the token permissions, publication of the same tested release succeeded. No new model build was needed. The private repository is [BOLD publication acceptance](https://github.com/bold-lab-ai/lite-eval-bold-publication-acceptance-2c413be2), release `v1`, commit `fd734263e9a3e08c706987f08c2f1d8958d25937`.

The downloaded GitHub ZIP was 23,274 bytes. Its revision matched the release. It returned fitness 16.0 over three seeds for a separate valid input and rejected a boolean input. The GitHub credential was absent from the release files. The earlier HTTP 403 blocker is resolved.
