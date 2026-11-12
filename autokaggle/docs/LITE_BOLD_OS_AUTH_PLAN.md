# Lite sign-in through BOLD OS

Prepared 12 November 2026. The collaborator can implement the integration now. The owner expects the sign-in setup to be available on 13 November 2026. This document is a plan, not evidence that BOLD OS sign-in is deployed.

## Approved outcome

Any active human member of the BOLD Slack workspace can use AutoKaggle Lite through BOLD OS sign-in. No manual email allowlist is needed. Existing projects, ownership, sharing, and research history must survive the change.

For now, allow any user with a verified email to use Lite. Keep email-code sign-in; a typed email alone must not establish identity. The temporary mode is an explicit owner-approved exception to the former lab-member restriction.

## Current implementation and resources

- AutoKaggle repository: https://github.com/yhg01/AutoKaggle
- Feature branch: `codex/agent-led-task-workflows`, PR https://github.com/yhg01/AutoKaggle/pull/17. This branch is deployed but is not merged into main.
- Lite: https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite
- Civo: cluster `ecc962fa-2f4c-4a3f-96c4-179af273fb7a`, region `lon1`, namespace `autokaggle-web`, deployment `lite`, configuration `lite-config`.
- BOLD OS repository: https://github.com/bold-lab-ai/bold-os
- BOLD OS site: https://bold-lab-ai.github.io/bold-os/
- Firebase project: `bold-d7ff2`; functions region: `europe-west2`.
- BOLD OS already uses Firebase provider `oidc.slack`. See `src/assets/js/bold.js`, `functions/index.js` (`signedInEmail`, `onlySlackSignUps`, `getMyAccess`), and `docs/REFERENCE.md`.
- AutoKaggle entry points: `autokaggle/lite.py` (`require_member`), `autokaggle/access.py`, `autokaggle/email_auth.py`, and `autokaggle/store.py`.
- The BOLD MCP credential is an agent integration credential. It must not authenticate human users or be placed in a browser.

The local BOLD OS worktree also contains unfinished compute-approval work. Preserve it. Use a separate worktree and branch from current BOLD OS main for this integration.

## Temporary email access

`AUTOKAGGLE_LITE_ACCESS_POLICY=verified_email` permits an authenticated email account to use Lite. `members` retains the previous allowlist rule and is the default when the setting is absent. Unknown settings fail closed. Keep `AUTOKAGGLE_PRIVATE_MODE=1`.

The policy changes admission to Lite. It does not grant administrator privileges, share all projects, or change execution limits. New sessions still require storage consent. Existing account IDs and ownership records stay unchanged.

Use `autokaggle.deploy.rollout` for an existing deployment. It preserves runtime additions and takes a private database backup. The base Lite deployer also preserves the selected access policy when its option is omitted.

Deployment evidence: the temporary mode is live on Civo as of 12 November 2026. The 134 focused tests and one live DeepSeek interview passed. Server checks confirmed verified non-member access, private project isolation, and no administrator access. All eight saved Lite projects were preserved. Email delivery and browser sign-in were not retested.

## Proposed sign-in flow

1. The researcher opens Lite or an existing project link and selects **Continue with BOLD OS**.
2. Lite starts a short-lived login transaction. Save a random state and a PKCE verifier on the server, bound to the browser session. Send only the challenge, registered client ID, and allowed callback to BOLD OS.
3. A BOLD OS page uses the existing Firebase/Slack sign-in. Reuse its current identity provider. Do not create a second independent Slack account system.
4. A BOLD OS function validates the Firebase identity and current BOLD workspace membership. A browser-supplied name, email, workspace ID, or member flag is not evidence of membership.
5. BOLD OS issues an opaque, single-use code with a short expiry, such as 60 seconds. Bind it to the client, exact callback, PKCE challenge, and authenticated account. Store only its hash. Return the code and state to Lite; never put a Firebase or Slack bearer token in the URL.
6. Lite checks state and exchanges the code and verifier with the fixed BOLD OS backend endpoint. Consume the code atomically. The response supplies the stable BOLD OS UID, Slack workspace/user IDs, verified contact details, and approved access.
7. Lite creates a secure, HttpOnly, SameSite session cookie and returns to the original local project path. Reject arbitrary return URLs.

Keep all Slack and Firebase privileged credentials inside BOLD OS. The exchange should not require a Firebase service-account key on Civo. The implementation must define a scoped session/status mechanism for continued membership checks; do not reuse the MCP token for this purpose.

## Membership and access rules

- Admit active human members of the BOLD workspace, including workspace guests, under the owner's instruction that anyone in BOLD Slack can use Lite.
- Exclude bots, deactivated users, and external Slack Connect participants who are not members of the BOLD workspace.
- Reuse BOLD OS's membership logic, but check freshness. An existing Firebase account or an old roster entry alone does not prove current membership. The current new-account hook is not a continuing-access check.
- Preserve the linked Slack identity check. Do not require that `sign_in_provider` always equals Slack: linking GitHub can change that value without removing the Slack identity.
- Check membership at login, then refresh it within a documented short interval, such as five minutes. Use verified Slack membership-change events to invalidate sessions sooner where available. Fail closed after cached approval expires if membership cannot be checked.
- Slack membership gives ordinary Lite access. Keep administrator privileges and compute approvals separate.
- Continue to enforce project ownership and explicit collaborator grants on every data operation.

## Existing-account migration

Store external identity links in a dedicated table with unique provider/subject keys. Use the stable BOLD OS UID and Slack workspace/user pair. Retain the existing AutoKaggle owner ID so project records need not be rewritten.

An existing user can link BOLD OS after proving both identities: their current verified-email session and the new BOLD OS sign-in. A session that has expired can use email verification once for linking. Do not merge owners automatically from an unverified email, a display name, or a client-supplied account ID. Report identity conflicts without transferring projects.

Define logout, session expiry, membership removal, and administrator recovery before launch. Remove the unrestricted verified-email entry path only after account migration and BOLD OS sign-in pass the release checks. Keep any recovery route explicitly administrator-controlled.

## Work split

| Owner | Work |
| --- | --- |
| BOLD OS collaborator | Sign-in bridge page; issue/exchange code functions; current membership check; revocation/status mechanism; emulator tests; BOLD OS review and Firebase deployment. |
| AutoKaggle collaborator | Login/callback/exchange routes; identity-link storage; secure sessions; membership refresh; migration; signed-out and denied-access pages. |
| Operator | Register the exact Lite client/callback, provide Firebase deployment access through the approved process, deploy both sides, and run real Slack acceptance tests. |

Read each repository's AGENTS.md before implementation. BOLD OS page merges and Firebase function deployments are separate. Deploy only the named functions; do not run a blanket Firebase deployment or enable Firebase Hosting. This work must not send Slack messages or email invitations without the required confirmation.

## Tests and release checks

Test the complete flow for an existing member, new member, guest, non-member, Slack Connect outsider, and deactivated member. Test an account that has Slack and linked GitHub identities. Confirm that none receives administrator privileges by signing in.

Test expired and reused codes, wrong state, wrong verifier, wrong callback, wrong issuer/audience where tokens are verified, concurrent exchanges, and failed membership lookup. Confirm that identity details cannot be changed by the browser.

Test existing-account linking, duplicate/conflicting links, project resume after logout, explicit collaboration, and denial of another user's private project. Check desktop and phone sign-in in private browser windows, as BOLD OS requires.

Before deployment, back up the Lite database and confirm no active interview or build jobs will be interrupted. Deploy BOLD OS support first, then Lite. Run real Slack sign-in before replacing `verified_email` with the new BOLD OS policy. Do not repurpose `members` to mean BOLD OS authentication.

If sign-in fails, restore the known working Lite source and the owner-approved temporary `verified_email` mode. Preserve identity links and projects. Do not use `AUTOKAGGLE_PRIVATE_MODE=0` as a rollback.

## References

- Slack sign-in: https://docs.slack.dev/authentication/sign-in-with-slack/
- Firebase ID-token verification: https://firebase.google.com/docs/auth/admin/verify-id-tokens
- Slack membership/profile changes: https://docs.slack.dev/reference/events/user_change/
- BOLD OS current membership checks: https://github.com/bold-lab-ai/bold-os/blob/main/functions/index.js
