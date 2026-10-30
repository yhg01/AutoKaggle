"""Operator OAuth helper checks; simulated exchanges do not prove Google consent."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import stat
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from autokaggle.deploy import configure_gmail as setup


CLIENT = {"client_id": "123-test.apps.googleusercontent.com", "client_secret": "test-secret"}


def client_file(tmp_path, **overrides):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"installed": {**CLIENT, "auth_uri": setup.AUTH_URL,
                                             "token_uri": setup.TOKEN_URL, **overrides}}))
    return path


def test_desktop_client_uses_only_google_addresses(tmp_path):
    path = client_file(tmp_path)
    assert setup.load_client(path) == CLIENT
    for values in ({"auth_uri": "https://evil.example/auth"}, {"token_uri": "http://oauth2.googleapis.com/token"},
                   {"client_secret": "bad\nsecret"}, {"client_id": "not-google"}):
        with pytest.raises(setup.SetupError):
            setup.load_client(client_file(tmp_path, **values))
    path.write_text(json.dumps({"web": CLIENT}))
    with pytest.raises(setup.SetupError, match="desktop"):
        setup.load_client(path)


def test_authorization_is_send_only_offline_with_pkce_and_state():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert setup.pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    url = setup.authorization_url(CLIENT, "http://127.0.0.1:1234/oauth/callback", "state-value", verifier)
    params = parse_qs(urlsplit(url).query)
    assert params["scope"] == [setup.SCOPE]
    assert params["include_granted_scopes"] == ["false"]
    assert params["access_type"] == ["offline"] and params["prompt"] == ["consent"]
    assert params["state"] == ["state-value"] and params["code_challenge_method"] == ["S256"]
    assert params["login_hint"] == [setup.SENDER]
    assert CLIENT["client_secret"] not in url and verifier not in url


@pytest.mark.parametrize("path", [
    "/oauth/callback?state=wrong&code=secret", "/oauth/callback?state=ok&state=ok&code=secret",
    "/oauth/callback?state=ok&code=a&code=b", "/other?state=ok&code=a",
    "https://evil.example/oauth/callback?state=ok&code=a", "/oauth/callback?state=ok",
    "/oauth/callback?state=ok&code=" + "x" * 9000,
])
def test_callback_rejects_wrong_state_paths_and_duplicate_parameters(path):
    with pytest.raises(setup.SetupError):
        setup.parse_callback(path, "ok")


def test_callback_state_required_for_success_and_denial():
    assert setup.parse_callback("/oauth/callback?state=ok&code=short-lived", "ok") == {"code": "short-lived"}
    assert "error" in setup.parse_callback("/oauth/callback?state=ok&error=access_denied", "ok")
    with pytest.raises(setup.SetupError):
        setup.parse_callback("/oauth/callback?state=wrong&error=access_denied", "ok")


def token_response(**overrides):
    return {"scope": setup.SCOPE, "refresh_token": "private-test-refresh-token-value", "token_type": "Bearer",
            "access_token": "temporary-not-saved", **overrides}


def test_exchange_validates_grant_and_does_not_store_access_token():
    calls = []
    def provider(request):
        calls.append(request)
        return httpx.Response(200, json=token_response())
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        result = setup.exchange_code(CLIENT, "authorization-code", "verifier", "http://127.0.0.1:123/oauth/callback", http_client=client)
    assert result["scopes"] == [setup.SCOPE]
    assert result["expected_sender"] == setup.SENDER and result["type"] == "authorized_user"
    assert "access_token" not in result
    assert str(calls[0].url) == setup.TOKEN_URL
    sent = parse_qs(calls[0].content.decode())
    assert sent["code_verifier"] == ["verifier"] and sent["client_secret"] == [CLIENT["client_secret"]]


@pytest.mark.parametrize("overrides", [
    {"scope": setup.SCOPE + " https://www.googleapis.com/auth/drive"}, {"scope": ""},
    {"refresh_token": None}, {"refresh_token": "tiny"}, {"refresh_token": "x" * 20 + "\n"},
    {"token_type": "Unknown"},
])
def test_wrong_scope_or_missing_refresh_never_saved(overrides):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=token_response(**overrides)))) as client:
        with pytest.raises(setup.SetupError):
            setup.exchange_code(CLIENT, "code", "verifier", "http://127.0.0.1:123/oauth/callback", http_client=client)


def test_provider_failure_does_not_expose_response():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(400, text="private-token-in-provider-response"))) as client:
        with pytest.raises(setup.SetupError) as failure:
            setup.exchange_code(CLIENT, "code", "verifier", "http://127.0.0.1:123/oauth/callback", http_client=client)
    assert "private-token" not in str(failure.value)


def test_private_writes_refuse_overwrite_and_symlinks(tmp_path):
    output = tmp_path / "private" / "credential.json"
    setup.write_private(output, "first")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(setup.SetupError):
        setup.write_private(output, "second")
    assert output.read_text() == "first"
    setup.write_private(output, "second", replace=True)
    assert output.read_text() == "second" and stat.S_IMODE(output.stat().st_mode) == 0o600
    link = tmp_path / "link"
    link.symlink_to(output)
    with pytest.raises(setup.SetupError):
        setup.write_private(link, "third")
    assert output.read_text() == "second"


def test_complete_loopback_flow_keeps_client_untouched_and_removes_private_url(tmp_path, monkeypatch, capsys):
    original = client_file(tmp_path)
    before = original.read_bytes()
    output, url_path = tmp_path / "private/credentials.json", tmp_path / "private/url.txt"
    monkeypatch.setattr(setup, "exchange_code", lambda *args, **kwargs: {"type": "authorized_user", "refresh_token": "private-test-token"})
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(setup.configure, original, output, url_path, timeout=5)
        deadline = time.monotonic() + 4
        while not url_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        params = parse_qs(urlsplit(url_path.read_text().strip()).query)
        callback = params["redirect_uri"][0]
        assert urlsplit(callback).hostname == "127.0.0.1"
        with httpx.Client(trust_env=False) as client:
            wrong = client.get(callback, params={"state": "wrong", "code": "private-code"})
            assert wrong.status_code == 400 and "private-code" not in wrong.text
            denied_host = client.get(callback, params={"state": params["state"][0], "code": "private-code"}, headers={"Host": "evil.example"})
            assert denied_host.status_code == 400
            accepted = client.get(callback, params={"state": params["state"][0], "code": "private-code"})
            assert accepted.status_code == 200 and accepted.headers["cache-control"] == "no-store"
        assert task.result(timeout=5) == output
    assert original.read_bytes() == before
    assert not url_path.exists() and stat.S_IMODE(output.stat().st_mode) == 0o600
    printed = capsys.readouterr().out
    assert "private-test-token" not in printed and "private-code" not in printed and setup.AUTH_URL not in printed


def test_refuses_reusing_client_path_for_credentials(tmp_path):
    original = client_file(tmp_path)
    with pytest.raises(setup.SetupError):
        setup.configure(original, original, tmp_path / "url", timeout=1, replace=True)
