"""Publish a tested Lite evaluator release to its own private GitHub repository.

Publishing pushes the tested commit unchanged. There are two ways to reach
GitHub. On a developer machine the gh command is used, so the credential stays
in gh's own store and this module never reads it. On a server with no git or
gh, AUTOKAGGLE_LITE_GITHUB_TOKEN supplies a token and all traffic is HTTPS from
this process.

Set AUTOKAGGLE_LITE_GITHUB_OWNER to the account or organization that holds the
evaluator repositories. Without it, publishing is unavailable.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time

MARKER = "BOLD AutoKaggle Lite evaluator for problem "
LOCAL = "local:evaluator-release"
KEEP = ("PATH", "HOME", "USER", "LOGNAME", "GH_TOKEN", "GH_HOST", "GH_CONFIG_DIR", "XDG_CONFIG_HOME", "SSL_CERT_FILE",
        "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy")


DIVERGED = "{} has commits on main that did not come from AutoKaggle Lite. Nothing was overwritten."
REFUSED = "GitHub did not accept the push to {} with this server's login."


class PublishError(Exception):
    """A cause that can be shown to the researcher."""


def owner():
    """The configured account or organization, or '' when publishing is not configured."""
    value = os.getenv("AUTOKAGGLE_LITE_GITHUB_OWNER", "").strip()
    if value and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", value):
        raise ValueError("AUTOKAGGLE_LITE_GITHUB_OWNER must be one GitHub account or organization name.")
    return value


def repository_name(project_id, title):
    """A stable name. The problem ID fragment keeps two problems with the same title apart."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")[:48].strip("-") or "problem"
    return f"lite-eval-{slug}-{re.sub(r'[^a-z0-9]', '', project_id.lower())[:8]}"


def address(account, name):
    return f"https://github.com/{account}/{name}"


def planned_address(state):
    """The address a new release should record: the saved repository, or the one publishing would create."""
    try:
        account = owner()
    except ValueError:
        return None
    if not account:
        return None
    saved = state.get("github")
    return saved["url"] if saved else address(account, state["repository_name"]) if state.get("repository_name") else None


def _summary(body):
    return {"id": body["id"], "full_name": body["full_name"], "owner": body["owner"]["login"], "name": body["name"],
            "url": body["html_url"], "private": bool(body["private"]), "description": body.get("description") or ""}


class _Client:
    """Repository lookups and creation, shared by both ways of reaching GitHub."""

    _checked = (0.0, (False, ""))
    _login = None

    def _api(self, path, method="GET", body=None):
        raise NotImplementedError

    def _ready(self):
        raise NotImplementedError

    def account(self):
        if not self._login:
            body = self._api("user")
            if not body:
                raise PublishError("The GitHub login on this server is not usable.")
            self._login = body["login"]
        return self._login

    def available(self):
        if time.monotonic() - self._checked[0] < 60:
            return self._checked[1]
        result = self._ready()
        if not result[0]:
            self._login = None
        self._checked = (time.monotonic(), result)
        return result

    def repository(self, reference):
        body = self._api(reference)
        return _summary(body) if body else None

    def create(self, account, name, description):
        holder = self._api("users/" + account)
        if not holder:
            raise PublishError(f"GitHub has no account or organization named {account}.")
        if holder.get("type") == "Organization":
            path = f"orgs/{account}/repos"
        elif account.lower() == self.account().lower():
            path = "user/repos"
        else:
            raise PublishError(f"{account} is another person's account. Use an organization or the account of this server's GitHub login.")
        body = self._api(path, "POST", {"name": name, "private": True, "description": description, "auto_init": False,
                                        "has_wiki": False, "has_projects": False})
        if not body:
            raise PublishError(f"This GitHub login may not create repositories under {account}.")
        return _summary(body)

    def git_url(self, repository):
        return f"https://github.com/{repository['full_name']}.git"


class GitHub(_Client):
    """GitHub through the gh and git commands. For a machine where a person has signed in with gh."""

    def __init__(self, command=None):
        self.command = command or os.getenv("AUTOKAGGLE_LITE_GH", "gh")

    def environment(self):
        return {**{name: os.environ[name] for name in KEEP if name in os.environ}, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}

    def _api(self, path, method="GET", body=None):
        """Return the decoded response, or None for HTTP 404."""
        argv = [self.command, "api", "-X", method, path] + (["--input", "-"] if body is not None else [])
        try:
            done = subprocess.run(argv, input=json.dumps(body) if body is not None else None, capture_output=True, text=True,
                                  timeout=60, env=self.environment())
        except (OSError, subprocess.SubprocessError) as exc:
            raise PublishError("GitHub could not be reached from this server.") from exc
        if done.returncode == 0:
            try:
                return json.loads(done.stdout)
            except ValueError as exc:
                raise PublishError("GitHub returned an unreadable response.") from exc
        if "HTTP 404" in done.stderr:
            return None
        raise PublishError("GitHub refused the request: " + (done.stderr.strip().splitlines() or ["no detail"])[-1][:300])

    def _ready(self):
        if not shutil.which(self.command):
            return False, "Publishing needs the gh command on this server, or a GitHub token in AUTOKAGGLE_LITE_GITHUB_TOKEN."
        try:
            self.account()
            return True, ""
        except PublishError:
            return False, "Publishing needs a GitHub login on this server. Sign in with gh, or provide AUTOKAGGLE_LITE_GITHUB_TOKEN."

    def git_options(self):
        # Clear any inherited helper, then let gh answer for this one command.
        return ["-c", "credential.helper=", "-c", f"credential.helper=!{self.command} auth git-credential"]

    def _git(self, repo, *args):
        env = {**self.environment(), "GIT_DIR": str(repo), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
               "GIT_TERMINAL_PROMPT": "0"}
        try:
            return subprocess.run(["git", *self.git_options(), *args], env=env, capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            raise PublishError("The Git command for publishing did not complete.") from exc

    def local_refs(self, repo):
        return _refs(self._git(repo, "for-each-ref", "--format=%(objectname) %(refname)", "refs/heads/main", "refs/tags").stdout.decode())

    def remote_refs(self, repo, repository):
        listed = self._git(repo, "ls-remote", self.git_url(repository))
        if listed.returncode:
            raise PublishError(f"GitHub did not allow reading {repository['full_name']} with this server's login.")
        return _refs(listed.stdout.decode())

    def push(self, repo, repository, names, local, before):
        pushed = self._git(repo, "push", "--atomic", self.git_url(repository), *[f"{name}:{name}" for name in names])
        if pushed.returncode:
            detail = pushed.stderr.decode(errors="replace").lower()
            raise PublishError(DIVERGED.format(repository["full_name"]) if "rejected" in detail or "fast-forward" in detail
                               else REFUSED.format(repository["full_name"]))

    def read(self, repo, commit, name):
        done = self._git(repo, "show", f"{commit}:{name}")
        return done.stdout if done.returncode == 0 else None


class TokenGitHub(_Client):
    """GitHub over HTTPS with a token, using no external command. For a server with no git or gh installed."""

    api = "https://api.github.com"

    def __init__(self, token, transport=None):
        self._token, self._transport = token, transport

    def _api(self, path, method="GET", body=None):
        import httpx
        headers = {"Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "autokaggle-lite"}
        try:
            with httpx.Client(transport=self._transport, timeout=30) as client:
                reply = client.request(method, f"{self.api}/{path}", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise PublishError("GitHub could not be reached from this server.") from exc
        if reply.status_code == 404:
            return None
        try:
            decoded = reply.json()
        except ValueError as exc:
            raise PublishError("GitHub returned an unreadable response.") from exc
        if reply.status_code >= 400:
            detail = decoded.get("message") if isinstance(decoded, dict) else None
            raise PublishError(f"GitHub refused the request: {str(detail or 'no detail')[:300]} (HTTP {reply.status_code})")
        return decoded

    def _ready(self):
        try:
            import dulwich  # noqa: F401
        except ImportError:
            return False, "Publishing with a token needs the dulwich package on this server."
        try:
            self.account()
            return True, ""
        except PublishError:
            return False, "The GitHub token on this server is not usable. It may have expired or may still await approval."

    def _remote(self, repository):
        from dulwich.client import get_transport_and_path
        client, path = get_transport_and_path(self.git_url(repository), username="x-access-token", password=self._token)
        return client, path.encode() if isinstance(path, str) else path

    def local_refs(self, repo):
        from dulwich.repo import Repo
        with Repo(str(repo)) as source:
            return {name.decode(): value.decode() for name, value in source.refs.as_dict().items()}

    def remote_refs(self, repo, repository):
        try:
            client, path = self._remote(repository)
            return {name.decode(): value.decode() for name, value in client.get_refs(path).refs.items() if value}
        except Exception as exc:  # The library raises several unrelated types. None of the detail is shown.
            raise PublishError(f"GitHub did not allow reading {repository['full_name']} with this server's token.") from exc

    def push(self, repo, repository, names, local, before):
        from dulwich.repo import Repo
        main = "refs/heads/main"
        with Repo(str(repo)) as source:
            # Git servers accept a rewritten branch unless the client refuses first. Refuse here.
            if main in names and before.get(main):
                ancestors = {entry.commit.id.decode() for entry in source.get_walker(include=[local[main].encode()])}
                if before[main] not in ancestors:
                    raise PublishError(DIVERGED.format(repository["full_name"]))

            def update(remote):
                seen = {name.decode(): value.decode() for name, value in remote.items()}
                if any(seen.get(name) != before.get(name) for name in names):
                    raise PublishError(f"{repository['full_name']} changed while it was being published. Try again.")
                return {name.encode(): local[name].encode() for name in names}

            try:
                client, path = self._remote(repository)
                result = client.send_pack(path, update, generate_pack_data=source.generate_pack_data, atomic=True)
            except PublishError:
                raise
            except Exception as exc:
                raise PublishError(REFUSED.format(repository["full_name"])) from exc
        if any((result.ref_status or {}).values()):
            raise PublishError(REFUSED.format(repository["full_name"]))

    def read(self, repo, commit, name):
        from dulwich.object_store import tree_lookup_path
        from dulwich.repo import Repo
        with Repo(str(repo)) as source:
            try:
                _, identifier = tree_lookup_path(source.get_object, source[commit.encode()].tree, name.encode())
                return source[identifier].data
            except KeyError:
                return None


def default_client():
    """A token on the server takes precedence. Otherwise use the gh login of the person running the application."""
    token = os.getenv("AUTOKAGGLE_LITE_GITHUB_TOKEN", "").strip()
    return TokenGitHub(token) if token else GitHub()


def _refs(text):
    refs = {}
    for line in text.splitlines():
        value, _, name = line.partition("\t") if "\t" in line else line.partition(" ")
        if re.fullmatch(r"[a-f0-9]{40}", value) and name:
            refs[name.strip()] = value
    return refs


def ensure_repository(project_id, title, name, saved, github, account, replace=False):
    """Return the private repository for this problem. Create it once; later calls reuse it by ID."""
    found = None
    if saved:
        found = github.repository(f"repositories/{saved['id']}")
        outside = found and found["owner"].lower() != account.lower()
        if (not found or outside) and not replace:
            raise PublishError((f"This problem is published at {found['url']}, which is outside {account}. Transfer that repository to {account}"
                                if outside else
                                f"The repository saved for this problem, {saved['url']}, no longer exists or this GitHub login cannot see it. Restore access")
                               + ", or publish with a new repository if the saved one was removed on purpose.")
        if not found or outside:
            found = None
    if not found:
        found = github.repository(f"repos/{account}/{name}")
        if found and MARKER + project_id not in found["description"]:
            raise PublishError(f"{found['full_name']} already exists and was not created for this problem. Rename or remove it first.")
        if not found:
            found = github.create(account, name, (MARKER + project_id + ". " + " ".join(str(title).split()))[:300])
    if not found["private"]:
        raise PublishError(f"{found['full_name']} is not private. Lite publishes evaluators only to private repositories.")
    return found


def push_release(repo, repository, commit, version, github):
    """Push main and the release tags in one all-or-nothing push without force, then confirm GitHub shows the tested commit."""
    tag, main = f"refs/tags/v{version}", "refs/heads/main"
    local = {name: value for name, value in github.local_refs(repo).items() if name == main or re.fullmatch(r"refs/tags/v\d+", name)}
    if local.get(tag) != commit or local.get(main) != commit:
        raise PublishError("The saved release does not match its tested commit. Build the evaluator again.")
    before = github.remote_refs(repo, repository)
    for name, value in local.items():
        if name != main and before.get(name, value) != value:
            raise PublishError(f"{repository['full_name']} has {name.rsplit('/', 1)[-1]} at a different commit. It was changed outside AutoKaggle Lite.")
    wanted = [name for name, value in local.items() if before.get(name) != value]
    if wanted:
        github.push(repo, repository, wanted, local, before)
    after = github.remote_refs(repo, repository)
    if after.get(tag) != commit or after.get(main) != local[main]:
        raise PublishError(f"{repository['full_name']} does not show the tested commit after the push.")
    try:
        recorded = json.loads(github.read(repo, commit, "evaluator.lock.json") or b"{}").get("repository")
    except ValueError:
        recorded = None
    return {"commit": commit, "tag": f"v{version}", "refs_pushed": len(wanted), "lock_repository": recorded,
            "address_recorded": isinstance(recorded, str) and recorded.lower() == repository["url"].lower()}
