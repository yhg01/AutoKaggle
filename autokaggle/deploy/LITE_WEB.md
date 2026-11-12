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


## Live source differs from this branch — checked 11 November 2026

The record below is the last release made from this branch. It is not what is running. On 11 November the `lite`
Deployment used ConfigMap `lite-source-358a9485e98b1481`, created on 9 November at 02:18 UTC, with source SHA256
`358a9485e98b14819127025e183a4b3a845ccb9c826ef1b490b405e2edb4c37e`. That release was made from the separate
`autokaggle-speedrun` checkout. Compared with this branch merged with `main`, the live source also has a
`scratch` or `speedrun` starting path (`PATCH /api/projects/{id}/onboarding`) and an uploaded-paper import. Neither
is in this branch or in `main`. This branch adds the evaluator build and publishing code, which the live source lacks.

A release from this branch would remove those live features. Combine the two lines of work first, or accept that
loss explicitly. The evaluator and publishing changes have not been deployed. On 11 November the five saved Lite
sessions were idle and the database passed its integrity check.

## GitHub publishing settings

Publishing is optional for Internal and is off on the hosted service. A downloadable release is sufficient. When an
owner is set, `deploy` reads a token from `$HOME/.config/autokaggle/lite-github.env` (`AUTOKAGGLE_LITE_GITHUB_TOKEN`) and
places it only in the `lite-secrets` Secret. Without an owner the token is not sent to the cluster. `deploy --github-owner NAME` sets `AUTOKAGGLE_LITE_GITHUB_OWNER` in
`lite-config`. The owner is kept on later deployments unless the option is given again; an empty value turns
publishing off. Both values enter the deployment's settings hash, so a change restarts Lite. The pinned runtime
packages include `dulwich` and `urllib3` for the token route. Hosted Lite cannot build evaluators, so these settings
have no effect until hosted builds exist. See [Publish to GitHub](../docs/LITE.md#publish-to-github).

Before a release, rehearse the pod locally: run the pinned image with a read-only root as user 1000, extract the source
archive, install `web-requirements.lock` with the init container's command, and start the application with the
generated settings. On 11 November this rehearsal found two start failures that the tests had missed.

## Last release from this branch — 5 November 2026, 18:12 UTC

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
