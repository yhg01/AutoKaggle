"""Private email accounts, bounded one-time codes, and revocable sessions."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from fastapi import HTTPException

from . import notifications, onboarding_setup

USER_COOKIE = "autokaggle_session"
CODE_SECONDS = 600
RESEND_SECONDS = 60
USER_SESSION_SECONDS = 30 * 24 * 60 * 60
GUESS_LIMIT = 5
EMAIL_HOUR_LIMIT = 6
EMAIL_DAY_LIMIT = 12
GLOBAL_HOUR_LIMIT = 100
GLOBAL_DAY_LIMIT = 400


class EmailAuth:
    def __init__(self, store, key):
        self.store, self.key = store, key
        with store.connection() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS email_accounts (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS email_codes (
                    id TEXT PRIMARY KEY, email_key TEXT NOT NULL, email TEXT NOT NULL,
                    digest TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0, delivered INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS email_codes_email ON email_codes(email_key, created);
                CREATE INDEX IF NOT EXISTS email_codes_created ON email_codes(created);
                CREATE TABLE IF NOT EXISTS email_guesses (email_key TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS email_guesses_time ON email_guesses(created);
                CREATE INDEX IF NOT EXISTS email_guesses_email ON email_guesses(email_key, created);
                CREATE TABLE IF NOT EXISTS email_sessions (
                    digest TEXT PRIMARY KEY, account TEXT NOT NULL, expires REAL NOT NULL);
            """)

    def _digest(self, purpose, value):
        return hmac.new(self.key, (purpose + ":" + value).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def available():
        return notifications.email_login_available()

    @staticmethod
    def _limited(message, retry):
        raise HTTPException(429, message, headers={"Retry-After": str(max(1, int(retry) + 1))})

    def _guess_limit(self, con, email_key, current):
        rows = con.execute("SELECT created FROM email_guesses WHERE email_key=? AND created>? ORDER BY created",
                           (email_key, current - CODE_SECONDS)).fetchall()
        if len(rows) >= GUESS_LIMIT:
            self._limited("Too many code attempts. Wait ten minutes, then request a new code.",
                          rows[0][0] + CODE_SECONDS - current)

    def request_code(self, value):
        try:
            email = onboarding_setup.validate_email(value).lower()
            if not email:
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, "Enter one valid email address.") from None
        if not self.available():
            raise HTTPException(503, "Email sign-in is not available yet. Please try again later.")
        current = time.time()
        email_key = self._digest("email", email)
        identifier = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(1_000_000):06d}"
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM email_codes WHERE created<?", (current - 2 * 86400,))
            con.execute("DELETE FROM email_guesses WHERE created<?", (current - CODE_SECONDS,))
            con.execute("DELETE FROM email_sessions WHERE expires<=?", (current,))
            self._guess_limit(con, email_key, current)
            last = con.execute("SELECT MAX(created) FROM email_codes WHERE email_key=?", (email_key,)).fetchone()[0]
            if last is not None and current - last < RESEND_SECONDS:
                self._limited("Wait one minute before requesting another code.", last + RESEND_SECONDS - current)
            for period, limit, key in ((3600, EMAIL_HOUR_LIMIT, email_key), (86400, EMAIL_DAY_LIMIT, email_key),
                                       (3600, GLOBAL_HOUR_LIMIT, None), (86400, GLOBAL_DAY_LIMIT, None)):
                query = "SELECT created FROM email_codes WHERE created>?"
                parameters = [current - period]
                if key is not None:
                    query += " AND email_key=?"
                    parameters.append(key)
                rows = con.execute(query + " ORDER BY created", parameters).fetchall()
                if len(rows) >= limit:
                    self._limited("Too many code requests. Please try again later.", rows[0][0] + period - current)
            # A resend cannot restore the guess budget or leave an older code valid.
            con.execute("UPDATE email_codes SET used=1 WHERE email_key=?", (email_key,))
            con.execute("INSERT INTO email_codes (id,email_key,email,digest,created,expires) VALUES (?,?,?,?,?,?)",
                        (identifier, email_key, email, self._digest("code", identifier + ":" + code), current, current + CODE_SECONDS))
        try:
            notifications.send_login_code(email, code)
        except notifications.MailUnavailable:
            with self.store.connection() as con:
                con.execute("UPDATE email_codes SET used=1 WHERE id=?", (identifier,))
            raise HTTPException(503, "The code could not be sent. Please try again later.") from None
        with self.store.connection() as con:
            con.execute("UPDATE email_codes SET delivered=1 WHERE id=? AND used=0", (identifier,))
        return {"challenge_id": identifier, "expires_in": CODE_SECONDS, "resend_after": RESEND_SECONDS}

    def verify(self, identifier, code):
        if (not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", identifier)
                or not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code)):
            raise HTTPException(400, "Enter the six-digit code from your email.")
        current = time.time()
        error = None
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            # Invalid identifiers also consume a bounded global verification budget.
            recent = con.execute("SELECT created FROM email_guesses WHERE created>? ORDER BY created", (current - 60,)).fetchall()
            if len(recent) >= 300:
                self._limited("Too many sign-in attempts. Please try again shortly.", recent[0][0] + 60 - current)
            row = con.execute("SELECT email_key,email,digest,expires,used,delivered FROM email_codes WHERE id=?", (identifier,)).fetchone()
            if not row or row[3] <= current or row[4] or not row[5]:
                con.execute("INSERT INTO email_guesses VALUES (?,?)", ("invalid", current))
                error = HTTPException(410, "This code expired or was replaced. Request a new code.")
            else:
                self._guess_limit(con, row[0], current)
                con.execute("INSERT INTO email_guesses VALUES (?,?)", (row[0], current))
                if not hmac.compare_digest(row[2], self._digest("code", identifier + ":" + code)):
                    error = HTTPException(401, "The code is not valid. Check the latest email and try again.")
                else:
                    # The immediate transaction makes consumption atomic across workers.
                    con.execute("UPDATE email_codes SET used=1 WHERE id=?", (identifier,))
                    account = con.execute("SELECT id FROM email_accounts WHERE email=?", (row[1],)).fetchone()
                    owner = account[0] if account else "account_" + secrets.token_hex(24)
                    if not account:
                        con.execute("INSERT INTO email_accounts VALUES (?,?,?)", (owner, row[1], current))
                    session = secrets.token_urlsafe(32)
                    con.execute("INSERT INTO email_sessions VALUES (?,?,?)",
                                (hashlib.sha256(session.encode()).hexdigest(), owner, current + USER_SESSION_SECONDS))
        if error:
            raise error
        return session

    def identity(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        with self.store.connection() as con:
            row = con.execute("SELECT a.id,a.email FROM email_sessions s JOIN email_accounts a ON a.id=s.account WHERE s.digest=? AND s.expires>?",
                              (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return {"owner": row[0], "email": row[1]} if row else None

    def revoke(self, token):
        if isinstance(token, str) and len(token) <= 256:
            with self.store.connection() as con:
                con.execute("DELETE FROM email_sessions WHERE digest=?", (hashlib.sha256(token.encode()).hexdigest(),))
