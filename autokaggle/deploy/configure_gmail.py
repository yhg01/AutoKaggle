"""Authorize the dedicated Gmail sender without changing the Drive connection.

This operator command uses a Google desktop OAuth client and a loopback callback.
It requests only Gmail send access. It prints private file paths, never tokens or
the authorization URL. Run it only when the account owner can approve consent.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

SCOPE = "https://www.googleapis.com/auth/gmail.send"
SENDER = "boldcoscientist@gmail.com"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PRIVATE = Path.home() / ".config/autokaggle"
DEFAULT_CLIENT = Path.home() / "Downloads/coscientist-intake-desktop-client.json"


class SetupError(Exception):
    """An operator-safe failure that contains no provider response or credential."""


def load_client(path):
    try:
        if path.stat().st_size > 32_768:
            raise SetupError("The Google client file is too large.")
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise SetupError("Cannot read the Google desktop client file.") from None
    client = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(client, dict):
        raise SetupError("Use a Google desktop client JSON file.")
    if client.get("auth_uri") not in {AUTH_URL, "https://accounts.google.com/o/oauth2/auth"} or client.get("token_uri") != TOKEN_URL:
        raise SetupError("The client must use the official Google authorization and token addresses.")
    identifier, secret = client.get("client_id"), client.get("client_secret")
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9._-]+\.apps\.googleusercontent\.com", identifier):
        raise SetupError("The Google desktop client ID is not valid.")
    if not isinstance(secret, str) or not 5 <= len(secret) <= 1024 or any(ord(c) < 33 or ord(c) > 126 for c in secret):
        raise SetupError("The Google desktop client secret is not valid.")
    return {"client_id": identifier, "client_secret": secret}


def pkce_challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")


def authorization_url(client, redirect_uri, state, verifier):
    return AUTH_URL + "?" + urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect_uri,
        "response_type": "code", "scope": SCOPE, "state": state,
        "code_challenge": pkce_challenge(verifier), "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false",
        "login_hint": SENDER,
    })


def parse_callback(path, state):
    """Validate state before accepting either an authorization code or an error."""
    if len(path) > 8192:
        raise SetupError("The authorization response is not valid.")
    parsed = urlsplit(path)
    if parsed.path != "/oauth/callback" or parsed.scheme or parsed.netloc or parsed.fragment:
        raise SetupError("The authorization response is not valid.")
    try:
        values = parse_qs(parsed.query, max_num_fields=20, keep_blank_values=True)
    except ValueError:
        raise SetupError("The authorization response is not valid.") from None
    supplied = values.get("state", [])
    if len(supplied) != 1 or not hmac.compare_digest(supplied[0].encode(), state.encode()):
        raise SetupError("The authorization response did not match this setup request.")
    if "error" in values:
        return {"error": "Google access was not granted. No credentials were saved."}
    code = values.get("code", [])
    if len(code) != 1 or not 1 <= len(code[0]) <= 4096:
        raise SetupError("The authorization response has no valid code.")
    return {"code": code[0]}


class LoopbackServer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, state):
        self.state = state
        self.result = None
        super().__init__(("127.0.0.1", 0), CallbackHandler)
        self.timeout = 0.5
        self.redirect_uri = f"http://127.0.0.1:{self.server_port}/oauth/callback"

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def handle_error(self, request, client_address):
        # Suppress callback request details from default HTTP server diagnostics.
        pass


class CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # The callback URL contains the short-lived authorization code.
        pass

    def do_GET(self):
        status = 400
        message = "The sign-in response was not accepted. Return to the Google consent page."
        if self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}":
            try:
                result = parse_callback(self.path, self.server.state)
                if self.server.result is None:
                    self.server.result = result
                    status = 200
                    message = ("Access was granted. You can close this tab and return to AutoKaggle."
                               if "code" in result else result["error"])
            except SetupError:
                pass
        data = message.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


def exchange_code(client, code, verifier, redirect_uri, *, http_client=None):
    values = {"client_id": client["client_id"], "client_secret": client["client_secret"],
              "code": code, "code_verifier": verifier, "redirect_uri": redirect_uri,
              "grant_type": "authorization_code"}
    try:
        if http_client is None:
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as http:
                response = http.post(TOKEN_URL, data=values)
        else:
            response = http_client.post(TOKEN_URL, data=values)
        if response.status_code != 200 or len(response.content) > 65_536:
            raise SetupError("Google did not complete the authorization. No credentials were saved.")
        result = response.json()
    except (httpx.HTTPError, ValueError, RecursionError):
        raise SetupError("Google authorization could not be confirmed. No credentials were saved.") from None
    if not isinstance(result, dict) or not isinstance(result.get("scope"), str) or set(result["scope"].split()) != {SCOPE}:
        raise SetupError("Google did not grant exactly Gmail send access. No credentials were saved.")
    refresh = result.get("refresh_token")
    if not isinstance(refresh, str) or not 20 <= len(refresh) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in refresh):
        raise SetupError("Google did not supply background access. Repeat consent to obtain a refresh token.")
    if str(result.get("token_type", "")).lower() != "bearer":
        raise SetupError("Google returned an unsupported authorization type.")
    return {"type": "authorized_user", **client, "refresh_token": refresh, "token_uri": TOKEN_URL,
            "scopes": [SCOPE], "expected_sender": SENDER}


def write_private(path, content, *, replace=False):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not replace:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise SetupError("The private output file already exists. Use a new path or explicitly allow replacement.") from None
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=".gmail-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def configure(client_path, output, url_file, *, timeout=600, replace=False):
    if len({p.resolve() for p in (client_path, output, url_file)}) != 3:
        raise SetupError("Use different paths for the desktop client, credentials, and authorization URL.")
    if output.exists() and not replace:
        raise SetupError("The Gmail credential file already exists. Use --replace only to replace this connection.")
    client = load_client(client_path)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    with LoopbackServer(state) as server:
        url = authorization_url(client, server.redirect_uri, state, verifier)
        write_private(url_file, url + "\n")
        print(f"Open the Google authorization address saved in: {url_file}", flush=True)
        print("Select the approved Gmail sender and grant send access. Waiting for consent.", flush=True)
        try:
            deadline = time.monotonic() + timeout
            while server.result is None and time.monotonic() < deadline:
                server.handle_request()
            if server.result is None:
                raise SetupError("Google consent timed out. No credentials were saved.")
            if "error" in server.result:
                raise SetupError(server.result["error"])
            credentials = exchange_code(client, server.result["code"], verifier, server.redirect_uri)
            write_private(output, json.dumps(credentials, indent=2) + "\n", replace=replace)
        finally:
            url_file.unlink(missing_ok=True)
    print(f"Gmail send credentials saved privately in: {output}", flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, default=DEFAULT_CLIENT)
    parser.add_argument("--output", type=Path, default=PRIVATE / "gmail-user.json")
    parser.add_argument("--url-file", type=Path, default=PRIVATE / "gmail-auth-url.txt")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--replace", action="store_true", help="Explicitly replace an existing Gmail credential file.")
    args = parser.parse_args()
    if not 30 <= args.timeout <= 1800:
        parser.error("Use a consent timeout from 30 to 1800 seconds.")
    try:
        configure(args.client, args.output, args.url_file, timeout=args.timeout, replace=args.replace)
    except (SetupError, OSError) as exc:
        print(str(exc) if isinstance(exc, SetupError) else "Cannot complete private Gmail setup. Check the local file paths and permissions.")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Gmail setup was cancelled.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
