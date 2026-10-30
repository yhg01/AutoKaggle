# Private AutoKaggle review service

This deployment uses the existing AutoKaggle cluster in London:
`ecc962fa-2f4c-4a3f-96c4-179af273fb7a`. It uses the separate
`autokaggle-web` namespace. The original intake site is a different service.

The HTTPS address is:
`https://ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/`.

## Access

Email sign-in gives each researcher a private workspace. Any email address can
register after its six-digit code is verified. Codes expire after ten minutes;
replacement requests wait 60 seconds. Five verification attempts apply across
resends within ten minutes. Send limits are six per hour and twelve per day per
address, and 100 per hour and 400 per day across the service. Limits persist in
the database. User sessions last up to 30 days and are revoked on sign-out.

The verified account email fills the private organizer contact for a new
challenge. Signing in again with the same email restores that account's work.
Account switching clears cached drafts and pending messages in the browser.
The administrator access code remains a separate fallback in
`$HOME/.config/autokaggle/web.env`, with mode 0600. Do not share that code
with researchers. Existing administrator-owned challenges remain separate from
email accounts unless an invitation grants access.

An organizer invitation gives access to one challenge. After sign-in, its
website, research ZIP, development submission form, and review chat use that
private session. A review-only session cannot create another workspace. The
challenge must pass its build checks before an invitation is available.

Civo blocks SMTP ports by default. Hosted email uses a separate Gmail API
sending connection over HTTPS. Consent is complete and the credential is
deployed in the `web-mail` Secret. Actual inbox receipt, sign-in, sign-out, and
returning to the same account passed in the browser. See
[email setup and verification](../docs/EMAIL_SETUP.md).

An operator can also create an invitation for manual sharing:

```sh
python -m autokaggle.deploy.web_invite PROJECT_UUID \
  --output $HOME/.config/autokaggle/review-link.txt
```

Use a new output file for each invitation. The command checks package readiness,
then saves a 24-hour, single-use link in a private file. It sends no email. Share
that link only with the intended reviewer. The link grants review and editing
access to that one challenge. A participant submission token is a different,
more limited credential.

## Release and storage

The service uses one process and one replica. SQLite and project locks require
this configuration. A 10 GiB Civo volume holds the project database, uploaded
data, private answers, packages, review grants, email accounts, and sign-in records. Replacing the application pod
keeps this volume. Deleting the PVC can delete its data; export and verify a
backup before storage changes.

The runtime image is a pinned official Python 3.12 slim image. It provides the
Linux library interface required by the scientific wheels. `web-requirements.lock` records the dependency versions used for local
validation. An init container installs those exact wheel versions into a private
runtime volume. The immutable source ConfigMap contains only application code,
prompt files, static files, and the dependency lock. Data, environment files, test outputs,
and operator credentials are excluded. A release hash identifies this source.

This method does not require a public image registry. A new pod needs HTTPS
access to the Python package index to prepare its runtime. A future release can
use a prebuilt private image with the same lock to remove that start-up dependency.

The app runs as a non-root user with a read-only root filesystem and no service
account token. A network policy limits inbound traffic to the ingress nodes.
Outbound traffic permits DNS and public HTTPS for model calls, Gmail sending,
and dependency installation. The Gmail path needs no SMTP egress. Access logs are disabled. The canonical HTTPS origin determines
secure cookies; the application does not trust forwarded request headers.

## Deploy

Run these commands from the repository root with the project Python environment:

```sh
python autokaggle/deploy/web-tls.py
python -m autokaggle.deploy.web deploy \
  --model-env /absolute/path/to/private/model.env \
  --gmail-credentials $HOME/.config/autokaggle/gmail-user.json
python -m autokaggle.deploy.web status
python -m autokaggle.deploy.web expose
```

The existing `gmail-user.json` connection is configured. For a new installation
or an explicit replacement, use `python -m autokaggle.deploy.configure_gmail`
after following the email setup guide. This credential grants only Gmail
sending access. It is separate from the Drive credential and the saved SMTP
password. The deployer stores it in the `web-mail` Kubernetes Secret, sent on
stdin. Later deployments preserve this Secret when `--gmail-credentials` is
omitted. To deploy without email before first setup, omit that argument; the
login page reports that email sign-in is unavailable.

The model file must contain `OPENROUTER_API_KEY`. The web deployment uses
`openai/gpt-6.1-sol`, with the application's medium conversation and high draft
reasoning settings. Model and administrator secrets are sent to Kubernetes on
stdin. The deployer does not print them. Each operation uses a temporary private
kubeconfig and preserves the operator's current context.

`deploy` installs the internal workload. `expose` requires an available workload
and a Ready certificate before it creates the HTTPS route. Repeat `deploy` after
source changes. Old immutable source ConfigMaps remain available for inspection.

## Limits

- CSV upload limit: 200 MiB, with the existing row and column bounds.
- Google Drive links are recorded; automatic import is still pending.
- Prediction submissions can use the trusted local scorer.
- The web container has no operator Civo credentials. Code submissions remain
  disabled until a separate restricted controller is connected and verified.
- Existing revision and package blockers still apply. Deployment does not mark
  an incomplete scientific definition as ready.
- The service is for private organizer review. Public competition publication,
  team enrollment, and final leaderboard release are separate work.

## Verified email release

The email release was verified with this application source hash:
`09c67ed62e0392bb5f58def7e09ecfb8db8d44ec6789b55f3d79ceda1069a146`.
The email verification record (local operational record; not included in this repository) reports the completed
browser, API, live OpenRouter, and automated checks. It also confirms that Gmail
configuration survived redeployment. The test totals are 139 relevant Python
tests and 103 Node client tests.

Mail receipt was checked only in the sender Gmail inbox. Other mail providers
were not checked. No real organizer review invitation was sent during this
release test; its shared mail transport and invitation rules have automated
coverage. Existing administrator-owned drafts remain separate from email
accounts. Use the earlier web record (local operational record; not included in this repository) for the website,
package, and prediction submission checks.
