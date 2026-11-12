# Internal Lite deployment

Lite uses a separate service on the existing AutoKaggle Civo cluster in London.
It has its own source, administrator key, database, and 1 GiB persistent volume.
Full keeps its existing deployment and data.

- Cluster: `ecc962fa-2f4c-4a3f-96c4-179af273fb7a`, region `lon1`.
- Namespace: `autokaggle-web`.
- Deployment and Service: `lite`.
- Persistent claim: `lite-data`.
- Host: `lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com`.
- Entry: [AutoKaggle Lite](https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite).

The root address redirects to `/lite`. Full keeps its normal entry on the
original host. Both services use one process and one replica for SQLite and
application locks. Lite has five bounded background workers for concurrent
interviews. Each project still has its own write lock. Do not scale replicas without changing the storage and lock
model first.


## Current release — 12 November 2026, 00:49 UTC

Released from commit `e06bcc6` of `internal-autokaggle-lite`. Source SHA256:

```text
43d8af461f709728c5e5160a5cb269af7ea06c412fa3d4ad23149b46dbbcc7a2
```

The immutable ConfigMap is `lite-source-43d8af461f709728`. The previous source is `lite-source-358a9485e98b1481`, with
SHA256 `358a9485e98b14819127025e183a4b3a845ccb9c826ef1b490b405e2edb4c37e`. Keep it available for rollback.

What changed for users: a new session opens with the paper and repository questions in the conversation, and the
Evaluator control is present. Evaluator builds are not available on this service, because they need Docker. GitHub
publishing is off; a downloadable release is sufficient for Internal. No GitHub owner or token is on the cluster.

The 9 November release was made from the separate `autokaggle-speedrun` checkout, whose work had not been committed.
That work was first combined into this branch. The combined source was compared with the live source file by file; no
live file was missing. `lite.py`, `lite_runner.py`, and `lite_gym_adapter.py` are byte-identical to the live files,
so saved contract versions stayed current.

Before release, all six saved sessions were idle. The database backup is
`/data/backups/pre-evaluator-opening-questions-20261112T004757Z.sqlite3`. Its integrity check passed.

After rollout, all six saved project bodies had the same hashes. The five built packages were still ready, and all
seven saved results remained. SQLite integrity passed. The member list, the model key, and the one-replica setting were
preserved. Anonymous access to `/lite` still redirects to sign-in and the anonymous API still returns 403. Full
retained generation 19 and the Speedrun preview retained generation 1.

Before release, 1,466 Python tests and 273 client checks passed. A local rehearsal of the pod passed. It used a
read-only root, user 1000, the init container's install command, and the generated settings. The pinned packages
also installed and imported in the pinned `linux/amd64` image.

Not checked after release: a signed-in session, a live interview, and the opening questions in a browser on the
hosted service. The model key is unchanged, and its OpenRouter account was low on credit on 11 November.

The Deployment apply needed `--force-conflicts` once. The 9 November release had set the source name and the two
hash annotations with a manual patch, so another field manager owned them. The deployer's manager owns them now.

## Earlier release — 9 November 2026, 02:19 UTC

Internal remains on its separate Civo host and persistent volume. The release
uses the shared application from the isolated `autokaggle-speedrun` worktree.

Source SHA256:

```text
358a9485e98b14819127025e183a4b3a845ccb9c826ef1b490b405e2edb4c37e
```

The immutable ConfigMap is `lite-source-358a9485e98b1481`. The previous source
is `lite-source-6c008a62f2f31bb1`, with SHA256
`6c008a62f2f31bb118b78a3103c57a281ad1095f89ed264886f08bb247264cc0`.
Keep that source available for rollback.

All five saved sessions were idle before restart. The database backup is
`/data/backups/pre-internal-three-paths-20261109T021529Z.sqlite3`.
Its integrity check passed. Its SHA256 is
`a0abe649f3a36b183867e599b813908f94e39085ad7accf7dd76bded41625e3b`.

After rollout, all 70 deployed source files matched the approved archive.
All five saved project bodies had the same hashes. All seven saved reports
remained present. SQLite integrity, TLS, the separate 1 GiB volume, approved
member access, and anonymous access denial passed. The existing member list,
private credentials, and one-replica setting were preserved. The root address
still leads to `/lite`. The login redirect now also sends `Cache-Control:
no-store`.

Full retained generation 19 and source
`4d4392ef37f7bd885d44bf0967407efe760b51155d7ace0a03790f3d597ae05f`.
Its complete deployment specification matched the record taken before release.
This release does not deploy the new Full Speedrun entry to the Full service.

Before release, 1,347 Python tests and 250 client checks passed. Live OpenRouter
checks passed for Full source import and ordinary interview entry. Local
Internal checks passed for ESOL and FreeSolv import, proposal review, ZIP and
config download, seeded sample execution, and result logging. A later change
preserved retry identifiers for existing URL-only imports; its 18 focused
source checks passed. These local checks are separate from the deployed
workflow check recorded below.

The normal deploy helper encountered field ownership from the previous
`kubectl-patch` source update. The running service stayed on the old source.
The release then used a guarded JSON patch for only the source ConfigMap
reference and matching source annotation. The patch checked both old values
before replacement. No broad ownership override was used.

The deployed Internal API workflow also passed. One disposable ESOL session
used two live OpenRouter calls with `openai/gpt-6.1-sol` and medium reasoning.
The source import proposed 22 fields. The test accepted an explicit engineering
contract for 96 public molecular records. Both downloaded ZIPs contained the
12 expected files, and each config matched its ZIP. Each version supplied
three visible seeds. Rebuilding the same version preserved its seeds.

The downloaded runner executed a training-target mean control on the local
CPU. The service accepted the measured records. A retry reused the saved
result, and a report with a missing seed was rejected. The website preview
returned successfully. A later budget revision blocked old downloads until
review and rebuild. The new package had a new contract version. Both measured
reports retained their correct version references.

The disposable project was deleted after these checks. The original five
sessions and seven reports remained. The temporary operator session was
revoked, and its local token file was removed. No sign-in email was sent.

These are API and local execution checks. Browser testing could not run
because browser control was disabled. No scientific reference was reproduced.
The batch adapter remains a template in the generated ZIP; this test supplied
its recorded adapter, data, and prediction fixture separately. The server
logged structurally checked results and did not independently reproduce them.

Private release receipts are under
`autokaggle/test-results/internal-civo-2026-11-09/`. They include the before
and after state, backup result, running file checks, and preservation checks.
Do not publish private session files or test data from that directory.

## GitHub publishing settings

Publishing is optional for Internal and is off on the hosted service. A downloadable release is sufficient. When an
owner is set, `deploy` reads a token from `$HOME/.config/autokaggle/lite-github.env` (`AUTOKAGGLE_LITE_GITHUB_TOKEN`) and
places it only in the `lite-secrets` Secret. Without an owner the token is not sent to the cluster. `deploy --github-owner NAME` sets `AUTOKAGGLE_LITE_GITHUB_OWNER` in
`lite-config`. The owner is kept on later deployments unless the option is given again; an empty value turns
publishing off. Both values enter the deployment's settings hash, so a change restarts Lite. The pinned runtime
packages include `dulwich` and `urllib3` for the token route. The Internal build runtime described below supplies tested releases for publishing. See [Publish to GitHub](../docs/LITE.md#publish-to-github).

Before a release, rehearse the pod locally: run the pinned image with a read-only root as user 1000, extract the source
archive, install `web-requirements.lock` with the init container's command, and start the application with the
generated settings. On 11 November this rehearsal found two start failures that the tests had missed.

## Earlier release — 5 November 2026, 18:12 UTC

The readiness gate update is deployed as source SHA256:

```text
6c008a62f2f31bb118b78a3103c57a281ad1095f89ed264886f08bb247264cc0
```

The ConfigMap is `lite-source-6c008a62f2f31bb1`. The previous source is
`lite-source-f9afaf4350b84dd8`, with SHA256
`f9afaf4350b84dd871055c9145e873c50c2e8c79f6da665b60c2a44324562a97`.
Use those recorded values for a source rollback if needed.

Before the update, all five sessions were idle. The backup at
`/data/backups/pre-lite-readiness-20261105T181117Z.sqlite3` passed integrity
validation. After rollout, all five saved project-body hashes and both saved
reports matched. Full's Deployment was unchanged. The new model schema and
private model configuration were present. Earlier built packages became stale
and require assessment and rebuilding under the new readiness rule.

Release verification passed 1,281 Python tests and 58 Lite/login client checks.
The three existing numeric-warning cases were retained. The
private operational receipts are `readiness-release-before.json` and
`readiness-release-after.json` in `autokaggle/test-results/lite-deploy/`.

The final read-only check passed at 18:15 UTC. All five projects were idle, with
ready packages, no recorded open decisions, and a saved result for the current
challenge version. Seven reports remained in the store, including two reports
from earlier versions. Each current report had `evidence_checked` status and
`independently_reproduced=false`. No training or independent reproduction was
performed by this deployment check.

HTTPS health, private login, member access, and anonymous denial for the known
project downloads passed. The SQLite integrity check returned `ok`. The Lite
replica was ready and its separate 1 GiB volume was bound. Full's specification
and generation matched the original record. The source digest was unchanged.
The credential-free receipt is `final-operational-receipt.json` in the same
local test-results directory.

## Initial release — 5 November 2026

The first Lite deployment passed HTTPS health, the root redirect, anonymous
access denial, member access, configured email sign-in, five-worker startup,
and SQLite integrity checks. Full's Deployment specification and generation
matched the record taken before this release. No Full restart or researcher
record change was needed. No email was sent by these checks.

Source SHA256:

```text
f9afaf4350b84dd871055c9145e873c50c2e8c79f6da665b60c2a44324562a97
```

The immutable source ConfigMap is `lite-source-f9afaf4350b84dd8`. The private
operational receipt is in `autokaggle/test-results/lite-deploy/release.json`.
The first live imports found a deployment error: Lite reads
`OPENROUTER_API_KEY`, while the original web deployer supplied only
`OPENAI_API_KEY`. The Lite Secret now supplies both names to the same private
key. A regression test checks the Secret and its container reference. Nine
deployment checks pass.

The correction restarted only Lite. The backup at
`/data/backups/pre-lite-model-key-20261105T175939Z.sqlite3` passed integrity
validation. All five saved project-body hashes matched after restart. The
existing Retry action resumed the saved imports. Five working sessions were
observed together at 18:01:57 UTC with five configured workers. This records
concurrent application jobs; it does not inspect the model provider's internal
scheduling.

These checks establish deployment and access behavior. The five published-task
interviews and submissions are recorded separately after their live runs.

## Access and services

Private mode and storage consent are enabled. Email sign-in alone does not
grant Lite membership.
Add only approved lab addresses to `AUTOKAGGLE_LITE_MEMBERS`. The deployer keeps
the current membership list unless `--members` is supplied. Project ownership
and collaborator checks still apply after membership is checked.

The Lite administrator key is saved in the private local file
`$HOME/.config/autokaggle/lite-web.env`, with mode 0600. It differs from the Full
administrator key. Keep keys and session cookies out of Git and test reports.
The service reuses the approved Gmail sending Secret. It uses OpenRouter model
`openai/gpt-6.1-sol` with medium conversation reasoning.

The application runs as a non-root user. Its root filesystem is read-only.
It has no Kubernetes service account token, host mounts, or Civo credentials.
The network policy permits ingress traffic from the existing ingress nodes,
DNS, and public HTTPS for approved application services. This web service does
not execute participant code. Report checks do not establish independent
reproduction.

## Release

From the repository root, use the project Python environment:

```sh
python -m autokaggle.deploy.lite_web tls
python -m autokaggle.deploy.lite_web deploy --model-env /absolute/path/to/private/.env
python -m autokaggle.deploy.lite_web status
python -m autokaggle.deploy.lite_web expose
```

The certificate uses the installed `autokaggle-letsencrypt` Issuer. The deployer
refuses to expose the route until the certificate and deployment are available.
It uses a temporary private kubeconfig for the fixed cluster. It does not change
the operator's current context.

For an approved membership change, use `deploy --members` with comma-separated
email addresses. An empty value limits access to administrators. Membership
updates restart Lite because the setting enters its deployment hash.

The source ConfigMap is immutable and named `lite-source-<digest prefix>`.
The source archive excludes local data, environment files, and test results.
Secrets are sent on standard input. Source updates must retain the claim,
private credentials, and one replica. Back up the SQLite database before an
update. The initial deployment starts with an empty database.

Before a release, check the generated source archive and run the affected tests.
After release, check HTTPS, anonymous denial, allowed-member access, email
configuration, the generated downloads, and the live model workflow. Confirm
that Full's deployment specification is unchanged. Record the release digest
and test results. Do not include credentials in the record.

## Test access

The five-task validation uses a short-lived session for the approved sender
account. An operator first confirms that the account already exists in Full's
verified email-account table. The operator then creates the account and an
eight-hour session in the separate Lite store. This sends no email and changes
no Full account or researcher record. The session file is private and excluded
from the release. It is not a new public login route.

Normal researchers use email sign-in on the Lite host. A project URL identifies
the saved session; it does not grant access. Users must also be approved lab
members and have ownership or collaborator access to that project.

## Restart and rollback

Wait for active interviews to finish before a planned restart. A restart keeps
saved records, but interrupts active model requests. The UI offers Retry for an
interrupted request. Do not delete a project or ask the researcher to repeat the
saved brief.

Use the fixed-cluster helper from this repository for every operation:

```python
from autokaggle.deploy.probe_cluster import Kubectl, private_kubeconfig

with private_kubeconfig() as config:
    kube = Kubectl(config)
    print(kube.run("rollout", "restart", "deployment/lite", "-n", "autokaggle-web"))
```

Before a source update, save the current source ConfigMap name and
`autokaggle/source-sha256` annotation. Make a SQLite backup with SQLite's backup
API and check `PRAGMA integrity_check`. Keep the backup on the persistent volume
or in the approved private backup location.

For a source rollback, patch only the `source` volume's ConfigMap reference and
its matching source annotation in `deployment/lite`. Use the recorded values.
Keep `lite-data`, the current keys, the allowlist, and the private-mode setting.
Do not restore an old database as part of a source rollback. Do not patch
`deployment/web`, which is Full.

After restart or rollback, repeat health, login, membership, download, and model
checks. Confirm the source annotation and compare saved project records. Old
immutable source ConfigMaps can remain available for a later rollback.

## Internal build runtime — 12 November

`lite_kubernetes.py` runs bounded build and acceptance jobs on the existing node. The jobs use the default container runtime, a non-root user, a read-only root, no added capabilities, no service-account token, and mounts for one job only. Each job has a deadline, 2 CPU and 4 GiB memory limits. Network policies block incoming traffic, private destinations, the application port, the cluster API, and metadata. Public HTTPS is available for dependencies. A short-lived model gateway is available on the Lite pod. Provider and GitHub credentials stay in the trusted web process.

This is an Internal lab service. Container isolation is not a claim of protection against all hostile code. Full's separate offline gVisor runner is unchanged. The Kubernetes control account can create, read, and remove jobs, and read pod status/logs. It cannot read secrets or execute commands in other pods.

Install the pinned build image on each eligible node before use. Set `AUTOKAGGLE_LITE_BUILD_RUNTIME=kubernetes`, an immutable `AUTOKAGGLE_LITE_BUILD_IMAGE`, the Lite data claim, and the pod IP from the downward API. Apply `lite_jobs.resources` and run its network checks before enabling builds. The source updater preserves existing runtime add-ons and makes a private SQLite backup:

```sh
python -m autokaggle.deploy.rollout lite --model-env /private/deepseek.env \
  --build-image IMAGE@sha256:DIGEST --github-owner OWNER --github-env /private/lite-github.env
python -m autokaggle.deploy.rollout web --model-env /private/deepseek.env
```

Use `yhg01` for test publication. Set the production owner only after access is checked. No new node is rented. The Lite data volume is 10 GiB; repository imports stop before the disk is full.

Civo volume expansion requires an offline volume. A larger PVC request does not prove the filesystem has grown. Stop Lite and wait for all build jobs and volume attachments to finish. Wait for controller expansion, then restart Lite and check the mounted capacity with `df`. Keep the private database backup. The 12 November expansion changed the existing Lite volume from 1 GiB to 10 GiB.

## Temporary email access — 12 November 2026

The owner approved access for any verified email while BOLD OS sign-in is prepared. Set `AUTOKAGGLE_LITE_ACCESS_POLICY=verified_email`; keep `AUTOKAGGLE_PRIVATE_MODE=1`. Existing member lists are retained but are not required in this mode. `members` restores the previous admission rule. The rollout command accepts `--lite-access-policy verified_email` only for the Lite service. It preserves the existing build runtime and other settings. See [the collaborator plan](../docs/LITE_BOLD_OS_AUTH_PLAN.md).


## Automatic evaluator publication — 12 November 2026

The approved BOLD connection uses `AUTOKAGGLE_LITE_GITHUB_OWNER=bold-lab-ai` and the private token file already configured for Lite. Enable automatic publication with the existing-service updater:

```sh
python -m autokaggle.deploy.rollout lite \
  --model-env "$HOME/.config/autokaggle/deepseek.env" \
  --github-env "$HOME/.config/autokaggle/lite-github.env" \
  --github-owner bold-lab-ai --auto-publish
```

The updater preserves the current access policy, runtime mounts, and database. It waits for active builds and publications to finish before replacing the service. The token stays in `lite-secrets`; build jobs receive no GitHub credential. Later updates preserve the automatic setting unless `--no-auto-publish` is supplied.

The tested commit is published only after acceptance checks pass. Publication failures retain the local release and show a retry action. A service restart during publication also shows a retry action. Retrying reuses the repository and release tag. This version does not resume an interrupted publication without a retry request. GitHub access is required to download the private repository or its ZIP.
