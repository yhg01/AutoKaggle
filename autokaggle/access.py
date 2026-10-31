"""Optional private deployment access with signed, expiring administrator sessions."""
from __future__ import annotations

from collections import deque
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .email_auth import EmailAuth, USER_COOKIE, USER_SESSION_SECONDS

ADMIN_COOKIE = "autokaggle_admin"
CSRF_COOKIE = "autokaggle_login_csrf"
SESSION_SECONDS = 8 * 60 * 60
CSRF_SECONDS = 10 * 60
ATTEMPT_WINDOW = 5 * 60
ATTEMPT_LIMIT = 5


class AccessGate:
    def __init__(self):
        setting = os.getenv("AUTOKAGGLE_PRIVATE_MODE", "0").strip().lower()
        if setting not in {"0", "1", "false", "true", "no", "yes", "off", "on"}:
            raise RuntimeError("AUTOKAGGLE_PRIVATE_MODE must be true or false.")
        self.enabled = setting in {"1", "true", "yes", "on"}
        code = os.getenv("AUTOKAGGLE_ADMIN_ACCESS_CODE", "")
        if self.enabled and not 32 <= len(code) <= 1024:
            raise RuntimeError("Private mode requires an administrator access code with 32 to 1024 characters.")
        self._code_digest = hashlib.sha256(code.encode()).digest()
        self._key = hmac.digest(code.encode(), b"autokaggle-private-access-v1", "sha256")
        base = urlparse(os.getenv("AUTOKAGGLE_PUBLIC_BASE_URL", ""))
        self._origin = f"{base.scheme}://{base.netloc}" if base.scheme and base.netloc else ""
        self._secure = base.scheme == "https"
        self._attempts: dict[str, deque] = {}
        self._all_attempts: deque = deque()
        self._lock = threading.Lock()
        self.email_auth = None
        self.store = None

    def attach_store(self, store):
        self.store = store
        self.email_auth = EmailAuth(store, self._key)

    def user(self, request):
        if not self.enabled or self.email_auth is None:
            return None
        # Cache identity only for this request. Each later request checks revocation.
        if not hasattr(request.state, "email_identity"):
            request.state.email_identity = self.email_auth.identity(request.cookies.get(USER_COOKIE, ""))
        return request.state.email_identity

    def secure_cookie(self, request: Request) -> bool:
        return self._secure or request.url.scheme == "https"

    def _sign(self, purpose: str, lifetime: int) -> str:
        payload = f"v1.{int(time.time()) + lifetime}.{secrets.token_urlsafe(24)}"
        signature = hmac.new(self._key, f"{purpose}.{payload}".encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def _valid(self, token: str, purpose: str, lifetime: int) -> bool:
        if not token or len(token) > 256:
            return False
        try:
            version, expires, nonce, signature = token.split(".")
            expiry = int(expires)
        except (ValueError, TypeError):
            return False
        current = time.time()
        if version != "v1" or not nonce or not current < expiry <= current + lifetime:
            return False
        expected = hmac.new(self._key, f"{purpose}.{version}.{expires}.{nonce}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected.encode(), signature.encode())

    def is_admin(self, request: Request) -> bool:
        identity = self.user(request)
        return bool(self.enabled and identity and self._valid(
            request.cookies.get(ADMIN_COOKIE, ""), "admin:" + identity["owner"], SESSION_SECONDS))

    def can_create(self, request: Request) -> bool:
        return not self.enabled or bool(self.user(request)) or self.is_admin(request)

    def owner(self, request: Request) -> str:
        identity = self.user(request)
        if identity:
            return identity["owner"]
        value = request.cookies.get("autokaggle_owner", "")
        if self.enabled and value == hmac.new(self._key, b"administrator-project-owner", hashlib.sha256).hexdigest():
            return ""
        # Stable account IDs are identifiers, never owner capabilities. An expired
        # email session must not fall back to a leftover administrator/review cookie.
        if self.enabled and (USER_COOKIE in request.cookies or value.startswith("account_")):
            return ""
        return value

    def auth_kind(self, request):
        if self.user(request):
            return "user"
        if self.is_admin(request):
            return "admin"
        if self.store is not None and self.store.list(self.owner(request)):
            return "reviewer" if self.enabled else "local"
        return "anonymous" if self.enabled else "local"

    def require_create(self, request: Request):
        if not self.can_create(request):
            raise HTTPException(401, "Sign in with your email to create a challenge.")

    def can_open(self, request: Request, store) -> bool:
        return self.can_create(request) or bool(store.list(self.owner(request)))

    def _require_origin(self, request: Request):
        expected = self._origin or str(request.base_url).rstrip("/")
        if request.headers.get("origin") != expected:
            raise HTTPException(403, "Sign in from this website.")
        if request.headers.get("sec-fetch-site", "same-origin") not in {"same-origin", "none"}:
            raise HTTPException(403, "Sign in from this website.")

    def _require_csrf(self, request):
        if not self.enabled:
            raise HTTPException(404, "Private sign-in is not enabled.")
        self._require_origin(request)
        token = request.cookies.get(CSRF_COOKIE, "")
        if not self._valid(token, "login-csrf", CSRF_SECONDS) or not hmac.compare_digest(token.encode(), request.headers.get("x-csrf-token", "").encode()):
            raise HTTPException(403, "The sign-in form expired. Reload this page, then try again.")

    async def _body(self, request, fields, optional=()):
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > 4096:
                raise HTTPException(400, "The sign-in request is not valid.")
        try:
            values = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise HTTPException(400, "The sign-in request is not valid.") from None
        if not isinstance(values, dict) or not set(fields) <= set(values) or not set(values) <= set(fields) | set(optional):
            raise HTTPException(400, "The sign-in request is not valid.")
        return values

    def _clear_identity_cookies(self, response, request, replacing=()):
        for name in (ADMIN_COOKIE, "autokaggle_owner", USER_COOKIE):
            if name not in replacing:
                response.delete_cookie(name, path="/", httponly=True, secure=self.secure_cookie(request), samesite="lax")

    def _record_attempt(self, request: Request):
        # One application process serves this private deployment. The total limit
        # also bounds memory and limits attempts from changing source addresses.
        current = time.monotonic()
        address = request.client.host if request.client else "unknown"
        with self._lock:
            cutoff = current - ATTEMPT_WINDOW
            while self._all_attempts and self._all_attempts[0] <= cutoff:
                self._all_attempts.popleft()
            for key in list(self._attempts):
                attempts = self._attempts[key]
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
                if not attempts:
                    del self._attempts[key]
            attempts = self._attempts.setdefault(address, deque())
            if len(attempts) >= ATTEMPT_LIMIT or len(self._all_attempts) >= 100:
                raise HTTPException(429, "Too many sign-in attempts. Wait five minutes, then try again.",
                                    headers={"Retry-After": str(ATTEMPT_WINDOW)})
            attempts.append(current)
            self._all_attempts.append(current)

    def register(self, app: FastAPI, static_dir: Path):
        @app.get("/login")
        def login_page():
            if not self.enabled:
                return RedirectResponse("/", status_code=303)
            return FileResponse(static_dir / "login.html")

        @app.get("/api/access")
        def access_state(request: Request, response: Response):
            result = {"private_mode": self.enabled, "can_create_projects": self.can_create(request),
                      "auth_kind": self.auth_kind(request),
                      "is_admin": self.is_admin(request),
                      "email_login_available": self.enabled and self.email_auth.available()}
            if self.enabled:
                token = self._sign("login-csrf", CSRF_SECONDS)
                response.set_cookie(CSRF_COOKIE, token, httponly=True, secure=self.secure_cookie(request),
                                    samesite="strict", path="/api/access", max_age=CSRF_SECONDS)
                result["csrf_token"] = token
            return result

        @app.post("/api/access/login")
        async def login(request: Request, response: Response):
            self._require_csrf(request)
            self._record_attempt(request)
            values = await self._body(request, {"access_code"})
            code = values.get("access_code")
            if not isinstance(code, str) or not 1 <= len(code) <= 1024 or set(values) != {"access_code"}:
                raise HTTPException(400, "Enter a valid access code.")
            try:
                supplied_digest = hashlib.sha256(code.encode()).digest()
            except UnicodeEncodeError:
                raise HTTPException(400, "Enter a valid access code.") from None
            if not hmac.compare_digest(supplied_digest, self._code_digest):
                raise HTTPException(401, "The access code is not valid.")
            secure = self.secure_cookie(request)
            identity = self.user(request)
            if not identity:
                raise HTTPException(401, "Verify your email to add administrator access.")
            self._clear_identity_cookies(response, request, (ADMIN_COOKIE, USER_COOKIE))
            purpose = "admin:" + identity["owner"]
            response.set_cookie(ADMIN_COOKIE, self._sign(purpose, SESSION_SECONDS), httponly=True,
                                secure=secure, samesite="lax", path="/", max_age=SESSION_SECONDS)
            response.delete_cookie(CSRF_COOKIE, path="/api/access", httponly=True, secure=secure, samesite="strict")
            return {"redirect": "/", "workspace_preserved": bool(identity)}

        @app.post("/api/access/email/request")
        async def request_email_code(request: Request):
            self._require_csrf(request)
            values = await self._body(request, {"email"})
            return await run_in_threadpool(self.email_auth.request_code, values["email"])

        @app.post("/api/access/email/verify")
        async def verify_email_code(request: Request, response: Response):
            self._require_csrf(request)
            values = await self._body(request, {"challenge_id", "code"}, {"access_code"})
            administrator = "access_code" in values
            if administrator:
                self._record_attempt(request)
                code = values["access_code"]
                if not isinstance(code, str) or not 1 <= len(code) <= 1024:
                    raise HTTPException(400, "Enter a valid administrator access key.")
                try:
                    supplied = hashlib.sha256(code.encode()).digest()
                except UnicodeEncodeError:
                    raise HTTPException(400, "Enter a valid administrator access key.") from None
                if not hmac.compare_digest(supplied, self._code_digest):
                    raise HTTPException(401, "The administrator access key is not valid. Correct it or uncheck administrator access.")
            previous = self.user(request)
            session = await run_in_threadpool(self.email_auth.verify, values["challenge_id"], values["code"])
            identity = self.email_auth.identity(session)
            if not identity:
                raise HTTPException(503, "Sign-in could not be confirmed. Request a new email code.")
            self.email_auth.revoke(request.cookies.get(USER_COOKIE, ""))
            self._clear_identity_cookies(response, request, (USER_COOKIE, ADMIN_COOKIE) if administrator else (USER_COOKIE,))
            secure = self.secure_cookie(request)
            response.set_cookie(USER_COOKIE, session, httponly=True, secure=secure,
                                samesite="lax", path="/", max_age=USER_SESSION_SECONDS)
            if administrator:
                response.set_cookie(ADMIN_COOKIE, self._sign("admin:" + identity["owner"], SESSION_SECONDS),
                                    httponly=True, secure=secure, samesite="lax", path="/", max_age=SESSION_SECONDS)
            response.delete_cookie(CSRF_COOKIE, path="/api/access", httponly=True, secure=secure, samesite="strict")
            return {"redirect": "/", "is_admin": administrator,
                    "workspace_preserved": bool(previous and previous["owner"] == identity["owner"])}

        @app.post("/api/access/logout")
        async def logout(request: Request, response: Response):
            self._require_csrf(request)
            await self._body(request, set())
            self.email_auth.revoke(request.cookies.get(USER_COOKIE, ""))
            if self.auth_kind(request) == "reviewer":
                with self.store.connection() as con:
                    con.execute("DELETE FROM review_grants WHERE session=?", (self.owner(request),))
            self._clear_identity_cookies(response, request)
            response.delete_cookie(CSRF_COOKIE, path="/api/access", httponly=True,
                                   secure=self.secure_cookie(request), samesite="strict")
            return {"redirect": "/login"}
