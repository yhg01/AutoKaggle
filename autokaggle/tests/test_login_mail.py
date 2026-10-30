"""Mail transport errors must not expose credentials or claim false delivery."""
import smtplib
import base64
import json

import httpx
import pytest

from autokaggle import notifications


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_PUBLIC_BASE_URL", "https://testserver")
    monkeypatch.setenv("AUTOKAGGLE_SMTP_PASSWORD", "test-only-secret")
    for part in ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"):
        monkeypatch.delenv("AUTOKAGGLE_GMAIL_" + part, raising=False)


def test_missing_mail_config_does_not_attempt_delivery(monkeypatch):
    monkeypatch.delenv("AUTOKAGGLE_SMTP_PASSWORD", raising=False)
    assert not notifications.email_login_available()
    with pytest.raises(notifications.MailUnavailable, match="not available"):
        notifications.send_login_code("tester@example.org", "123456")


def test_transport_has_tls_and_private_code_in_body(configured, monkeypatch):
    recorded = {}
    class Transport:
        def __init__(self, host, port, *, context, timeout):
            assert host == "smtp.gmail.com" and port == 465
            assert context.check_hostname and timeout == 15
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def login(self, username, password):
            assert password == "test-only-secret"
        def send_message(self, message):
            recorded["message"] = message
            return {}
    monkeypatch.setattr(notifications.smtplib, "SMTP_SSL", Transport)
    notifications.send_login_code("tester@example.org", "123456")
    message = recorded["message"]
    assert message["To"] == "tester@example.org"
    assert "123456" in message.get_content()
    assert "123456" not in message["Subject"]
    assert "10 minutes" in message.get_content()
    assert "test-only-secret" not in message.as_string()


@pytest.mark.parametrize("failure", [smtplib.SMTPAuthenticationError(535, b"private-provider-text"),
                                     TimeoutError("private-provider-text")])
def test_transport_failures_return_safe_message(configured, monkeypatch, failure):
    def fail(*args, **kwargs): raise failure
    monkeypatch.setattr(notifications.smtplib, "SMTP_SSL", fail)
    with pytest.raises(notifications.MailUnavailable) as result:
        notifications.send_login_code("tester@example.org", "123456")
    assert "private-provider-text" not in str(result.value)
    assert "could not be sent" in str(result.value)


@pytest.mark.parametrize("code", ["12345", "1234567", "１２３４５６", "12\n456"])
def test_transport_rejects_invalid_codes(configured, code):
    with pytest.raises(notifications.MailUnavailable):
        notifications.send_login_code("tester@example.org", code)


@pytest.mark.parametrize("failure_stage", [None, "refresh", "send"])
def test_gmail_https_transport_binds_sender_and_does_not_retry(configured, monkeypatch, failure_stage):
    for part in ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"):
        monkeypatch.setenv("AUTOKAGGLE_GMAIL_" + part, "test-" + part)
    monkeypatch.delenv("AUTOKAGGLE_SMTP_PASSWORD")
    calls = []
    def transport(request):
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            assert request.url.path == "/token"
            return httpx.Response(400 if failure_stage == "refresh" else 200,
                                  json={"access_token": "test-access-token", "error": "private-provider-text"})
        assert str(request.url) == "https://gmail.googleapis.com/gmail/v1/users/boldcoscientist%40gmail.com/messages/send"
        assert request.headers["authorization"] == "Bearer test-access-token"
        message = base64.urlsafe_b64decode(json.loads(request.content)["raw"])
        assert b"123456" in message and b"To: tester@example.org" in message
        return httpx.Response(403 if failure_stage == "send" else 200,
                              json={"id": "test-mail-id", "error": "private-provider-text"})
    real_client = httpx.Client
    monkeypatch.setattr(notifications.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(transport), **kwargs))
    assert notifications.email_login_available()
    if failure_stage:
        with pytest.raises(notifications.MailUnavailable) as result:
            notifications.send_login_code("tester@example.org", "123456")
        assert "private-provider-text" not in str(result.value)
    else:
        notifications.send_login_code("tester@example.org", "123456")
    assert len(calls) == (1 if failure_stage == "refresh" else 2)
