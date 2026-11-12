# Full Speedrun preview on Civo

This is a separate test service on the existing AutoKaggle cluster. It uses
the Full workflow, including the public-data research controls already on the
main live service. It also includes the new paper and repository entry path.

- URL: https://speedrun.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/
- Cluster: `ecc962fa-2f4c-4a3f-96c4-179af273fb7a`, `lon1`.
- Namespace: `autokaggle-web`.
- Deployment and Service: `speedrun-preview`.
- Source ConfigMap: `speedrun-source-d53143a70e6d0af1`.
- TLS certificate: `autokaggle-speedrun-tls`.

The release source SHA256 is:

```text
d53143a70e6d0af16af09303e56267b89999643e24f48e0a632056edcf68e1fa
```

## Data and access

**This preview has temporary storage.** Its database and uploads use a 1 GiB
`emptyDir` volume. A container restart keeps this volume. Replacing or removing
the pod deletes the preview data. Export required test records before a source
update or cleanup. Do not use this link for durable researcher work.

The preview has its own administrator credential, configuration, database, and
sessions. It does not mount Full or Internal data. Private access, email sign-in,
profile requirements, and storage consent remain active. The normal entry opens
the agent. A saved interview resumes without repeating the entry choice.

The preview uses the approved OpenRouter connection and the existing Gmail
send-only Secret. Its separate administrator key is stored locally in
`~/.config/autokaggle/speedrun-preview.env`, with mode `0600`. Do not share that
file or copy its contents into test reports. No sign-in email is sent by the
deployment checks.

## Resource and execution limits

The service has one replica and two bounded background workers. The web process
requests 250m CPU and 512 MiB RAM, with limits of two CPUs and 2 GiB RAM. Its init
container installs the pinned runtime dependencies. It does not rent a new VM,
create a persistent volume, or request a GPU.

The pod has a separate ServiceAccount, no service-account token, a read-only
root filesystem, and restricted network access. It has no execution-controller
or Civo credentials. Hosted participant execution remains disabled. Importing a
paper or repository does not execute its code or bypass the Full checks.

## Deployment and checks

The preview was prepared from the isolated `autokaggle-speedrun` worktree after
the existing public-data research changes were integrated. The integrated
Python suite passed 1,374 tests. The complete Node suite passed 252 tests.

The preview was ready on 9 November 2026 at 02:34 UTC. TLS, health, the login
page, and all 72 deployed source-file hashes passed. Anonymous users see no
projects, cannot create a project, and cannot open the Internal API. The model
configuration selects `openai/gpt-6.1-sol` through OpenRouter. This deployment
check sent no model request or sign-in email.

Full retained generation 19 and source
`4d4392ef37f7bd885d44bf0967407efe760b51155d7ace0a03790f3d597ae05f`.
Internal retained generation 4 and source
`358a9485e98b14819127025e183a4b3a845ccb9c826ef1b490b405e2edb4c37e`.
Both deployment specifications and the list of persistent volumes matched
their records before preview creation.

The operator script and private receipts are in the ignored directory
`autokaggle/test-results/speedrun-preview-2026-11-09/`. `preview.py prepare`
freezes the source archive and its per-file hashes. `deploy --expected SHA`
checks that exact candidate before creating only the named preview resources.
It stops if those resource names already exist. `expose` requires a ready pod
and TLS certificate. `verify` checks the source files, access rules, and the
unchanged Full and Internal deployment specifications.

Do not run the standard Full or Internal deployment commands to update this
preview. They target the existing services. The preview uses its own resource
names and application label. Its label does not select the Full controller
access policy.

Browser testing remains pending. The browser tool reports that Browser use is
disabled in this session. Health, source, and API access checks are not evidence
of the requested browser interviews or complete market benchmark runs.

## Cleanup

Export any required preview records first. Then remove only the named preview
Ingress, Deployment, Service, ServiceAccount, network policy, configuration,
source ConfigMap, credential Secret, and TLS certificate. Removing the
Deployment deletes its temporary dataset and sessions. Remove its local
credential file when it is no longer needed. Keep Full, Internal, the shared
mail Secret, the TLS issuer, and their storage unchanged.
