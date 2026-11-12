"""Loopback model gateway for one evaluator build job.

The coding agent receives a one-job token and this gateway's address. The real
provider key stays in the application process. The gateway pins the model,
bounds the number of requests, and records usage. It forwards nothing else.
It forwards OpenAI-style chat requests to the selected provider's endpoint.
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

UPSTREAM = "https://openrouter.ai/api/v1"
MAX_BODY = 8 * 1024 * 1024
ROUTES = {"/v1/chat/completions": "/chat/completions", "/v1/responses": "/responses"}


class Gateway:
    def __init__(self, key, model, *, max_requests=150, lifetime_seconds=3600, bind="127.0.0.1", upstream=UPSTREAM, request_fields=None):
        if not key:
            raise ValueError("The model provider key is not configured.")
        self._key, self.model, self.max_requests, self.upstream = key, model, max_requests, upstream.rstrip("/")
        self.request_fields = dict(request_fields or {})
        self.token = secrets.token_urlsafe(32)
        self._expires = time.monotonic() + lifetime_seconds
        self._lock = threading.Lock()
        self.usage = {"requests": 0, "rejected": 0, "input_tokens": 0, "output_tokens": 0, "models": [], "provider_errors": 0, "last_provider_status": None}
        self._server = ThreadingHTTPServer((bind, 0), self._handler())
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._expires = 0
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()

    def _admit(self, token, body):
        """Return (status, message). Count every refused request."""
        with self._lock:
            reason = None
            if not hmac.compare_digest(token.encode(), self.token.encode()):
                reason = (401, "Unknown build token.")
            elif time.monotonic() > self._expires:
                reason = (403, "This build's model allowance has expired.")
            elif body.get("model") != self.model:
                reason = (403, "This build may only use its approved model.")
            elif self.usage["requests"] >= self.max_requests:
                reason = (429, "This build reached its model request allowance.")
            if reason:
                self.usage["rejected"] += 1
                return reason
            self.usage["requests"] += 1
            return 200, ""

    def _record(self, payload):
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
            usage = usage or payload["response"].get("usage")
        with self._lock:
            model = payload.get("model") if isinstance(payload, dict) else None
            if isinstance(model, str) and model not in self.usage["models"] and len(self.usage["models"]) < 8:
                self.usage["models"].append(model)
            if isinstance(usage, dict):
                for source, target in (("prompt_tokens", "input_tokens"), ("input_tokens", "input_tokens"),
                                       ("completion_tokens", "output_tokens"), ("output_tokens", "output_tokens")):
                    if type(usage.get(source)) is int:
                        self.usage[target] += usage[source]

    def _handler(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *_):
                pass

            def _reply(self, status, message):
                data = json.dumps({"error": {"message": message, "code": status}}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._reply(404, "This gateway only forwards model requests.")

            def do_POST(self):
                route = ROUTES.get(self.path.split("?", 1)[0])
                if not route:
                    return self._reply(404, "This gateway only forwards model requests.")
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    return self._reply(411, "A request length is required.")
                if not 0 < length <= MAX_BODY:
                    return self._reply(413, "The model request is too large.")
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw)
                    if not isinstance(body, dict):
                        raise ValueError
                except ValueError:
                    return self._reply(400, "Send a JSON model request.")
                token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                status, message = gateway._admit(token, body)
                if status != 200:
                    return self._reply(status, message)
                if gateway.request_fields:
                    # The application, not the job, selects the reasoning setting for its provider.
                    for name in ("reasoning", "reasoning_effort", "thinking"):
                        body.pop(name, None)
                    body.update(gateway.request_fields)
                if body.get("stream"):
                    # Ask for token counts on streamed responses, so the build record can report them.
                    body["stream_options"] = {**(body["stream_options"] if isinstance(body.get("stream_options"), dict) else {}), "include_usage": True}
                if gateway.request_fields or body.get("stream"):
                    raw = json.dumps(body).encode()
                headers = {"Authorization": "Bearer " + gateway._key, "Content-Type": "application/json",
                           "Accept": self.headers.get("Accept", "application/json"), "X-Title": "BOLD AutoKaggle Lite evaluator build"}
                try:
                    with httpx.Client(timeout=httpx.Timeout(600, connect=20)) as client:
                        with client.stream("POST", gateway.upstream + route, content=raw, headers=headers) as upstream:
                            with gateway._lock:
                                gateway.usage["last_provider_status"] = upstream.status_code
                                gateway.usage["provider_errors"] += upstream.status_code >= 400
                            self.send_response(upstream.status_code)
                            self.send_header("Content-Type", upstream.headers.get("content-type", "application/json"))
                            self.send_header("Cache-Control", "no-store")
                            self.send_header("Connection", "close")
                            self.end_headers()
                            pending = b""
                            whole = b""
                            stream = "text/event-stream" in upstream.headers.get("content-type", "")
                            for chunk in upstream.iter_bytes():
                                self.wfile.write(chunk)
                                self.wfile.flush()
                                if stream:
                                    pending += chunk
                                    *lines, pending = pending.split(b"\n")
                                    for line in lines:
                                        if line.startswith(b"data:") and b'"usage"' in line:
                                            try:
                                                gateway._record(json.loads(line[5:]))
                                            except ValueError:
                                                pass
                                elif len(whole) < MAX_BODY:
                                    whole += chunk
                            if not stream:
                                try:
                                    gateway._record(json.loads(whole))
                                except ValueError:
                                    pass
                except (httpx.HTTPError, OSError):
                    with gateway._lock:
                        gateway.usage["provider_errors"] += 1
                    # The client sees a closed or failed response. Never echo provider details or the key.
                    try:
                        self._reply(502, "The model provider did not complete the request.")
                    except OSError:
                        pass

        return Handler
