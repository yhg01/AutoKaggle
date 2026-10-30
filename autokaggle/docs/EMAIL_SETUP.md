# Email sign-in and organizer invitations

The sender is `boldcoscientist@gmail.com`. AutoKaggle uses the Gmail API over HTTPS for the Civo service. Civo blocks outbound SMTP ports 25, 465, and 587 by default. An application network rule alone does not remove that block. [Civo FAQ](https://www.civo.com/docs/faq).

The Gmail connection requests only `https://www.googleapis.com/auth/gmail.send`. It can send mail but cannot read the inbox. It uses a separate credential file from the Drive connection. Researchers need access to their own email address; they do not grant Google account access. [Google scope reference](https://developers.google.com/workspace/gmail/api/auth/scopes).

## Sender connection

The Gmail consent step is complete. The private sending credential is deployed
in the `web-mail` Secret. The instructions below are for a new installation or
an explicit replacement of that connection. An ordinary application deployment
does not require another consent step.


1. Enable the Gmail API in the Google Cloud project that contains the existing desktop OAuth client.
2. Run the setup command below on your computer. It saves the Google consent address in a private file and waits for ten minutes.
3. Open the address from that file in a browser on that computer. Select `boldcoscientist@gmail.com` and grant Gmail sending access. The local callback finishes the setup.
4. Deploy with the resulting credential file. Then complete the real delivery and sign-in checks below.

```sh
python -m autokaggle.deploy.configure_gmail \
  --client /absolute/path/to/desktop-oauth-client.json \
  --output $HOME/.config/autokaggle/gmail-user.json \
  --url-file $HOME/.config/autokaggle/gmail-auth-url.txt

python -m autokaggle.deploy.web deploy \
  --model-env /absolute/path/to/private/model.env \
  --gmail-credentials $HOME/.config/autokaggle/gmail-user.json
```

Run these commands from the repository root with the project Python environment. The helper uses a local callback, state validation, and PKCE. It checks that Google granted exactly the sending scope. It writes credentials with mode 0600 and removes the temporary consent-address file. Existing credentials require an explicit `--replace`; use that option only when replacing this Gmail connection. The helper does not change Drive credentials.

The deployer loads Gmail credentials into the separate Kubernetes Secret `web-mail`. It preserves this Secret when a later deployment omits `--gmail-credentials`. The runtime refreshes access through Google and sends through the approved sender's Gmail API endpoint. It uses public HTTPS egress; SMTP egress is not needed. Google receives the message in the format required by its [sending API](https://developers.google.com/workspace/gmail/api/guides/sending).

The canonical review address is:
`https://ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com`.

An optional SMTP configuration belongs in a private file such as `$HOME/.config/autokaggle/mail.env`. The BOLD Civo service uses the Gmail API over HTTPS. Do not copy passwords, refresh tokens, consent URLs, or credential files into source control, screenshots, or logs.

## Researcher sign-in

- Open `/login`, enter an email address, and enter the six-digit code from the message. Any verified email address can create its own private workspace. There is no registration allowlist.
- A code works once and expires after ten minutes. A new code replaces the previous code. Wait at least 60 seconds before requesting another.
- Each email address has five verification attempts within ten minutes, across replacement codes. Send limits are six per hour and twelve per day per address. Global limits are 100 per hour and 400 per day. These limits use rolling windows and persist across restarts.
- A user session lasts up to 30 days. Sign out revokes that session on the server. Sign-in and sign-out clear stored draft text from the prior browser account and update other open tabs.
- Signing in with the same email restores access to that account's challenges. Another account cannot open those challenges through a project URL. Administrator-owned challenges remain separate unless a review invitation grants access.
- The verified account email fills the private organizer contact for a new challenge. It is excluded from participant packages. An invitation can grant review access to an existing challenge without granting permission to create other challenges.
- Administrator access remains a separate, collapsed option on the sign-in page. Use it for operator access, not as a shared researcher account.

Email codes are an MVP access method. This is not a claim about Kaggle's internal authentication system. Competition creation, review, and publication remain separate.

## Organizer review messages

A ready draft sends a review invitation only after its required definition and application checks pass. The message includes the measured development result and links to the website, ZIP, submission test, and review chat. It does not include final test scores.

The private review link expires after 24 hours and works once. It grants a seven-day session for that challenge. Open the sign-in link first, then use the other links in the same browser. The website, ZIP, and submission links contain no login token.

**Request changes** opens a review conversation with the prior interview, facts, and measured results. Rebuild the package after a change before sending a new invitation. An unchanged build does not send another invitation while its earlier link or review session remains valid. **Send a new review link** explicitly replaces unused links for the current ready version and preserves active review sessions.

The interface distinguishes missing configuration, failed delivery, and a message accepted by Gmail. Acceptance does not establish arrival in the recipient's inbox. A failed send does not consume the challenge submission allowance. Review messages and sign-in codes use the same private sending connection.

## Verification status

The hosted email flow passed on 30 October 2026. The browser checks confirmed
actual code receipt in the sender Gmail inbox, rejection of an incorrect code,
successful sign-in, sign-out, and a second code restoring the same saved project.
A real conversation through OpenRouter with `openai/gpt-6.1-sol` also succeeded
after email sign-in.

API checks confirmed that a used code returns 410, anonymous project creation
returns 401, and another account's project returns 404. Legacy administrator
access and an existing research ZIP remained available. The Gmail configuration
survived another application deployment. The release passed 139 relevant Python
tests and 103 Node client tests. See the email verification record (local operational record; not included in this repository).

Delivery was tested only to the sender Gmail inbox. Delivery to other providers
has not been checked. Organizer review invitations use the same mail transport
and have automated coverage, but no real review invitation was sent in this
verification run. Earlier deployed checks verified the single-use review-link
exchange and project access without sending mail. Legacy administrator-owned
drafts remain separate from email accounts. Public competition launch remains
a separate step.
