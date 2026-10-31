import io
import tarfile
import json

import pytest

from autokaggle.deploy.web import bundle, resources, WEB_IMAGE, mail_settings, gmail_settings


def test_release_bundle_contains_prompts_and_excludes_local_state():
    payload, digest = bundle()
    assert bundle() == (payload, digest)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        names = set(archive.getnames())
    assert {"autokaggle/prompts/conversation.md", "autokaggle/prompts/revision.md",
            "autokaggle/prompts/organizer.md", "autokaggle/static/login.html",
            "autokaggle/access.py", "autokaggle/observability.py", "autokaggle/static/internal.html",
            "autokaggle/static/internal.js", "autokaggle/static/internal.css",
            "autokaggle/static/internal-data.js",
            "autokaggle/static/interface-switch.js", "autokaggle/static/interface-switch.css",
            "autokaggle/deploy/web-requirements.lock"} <= names
    assert "autokaggle/scripts/review_internal.py" not in names
    assert not any("/.env" in n or "/data/" in n or "/tests/" in n or "/test-results/" in n for n in names)
    assert not any(n.endswith("verification.json") for n in names)


def test_web_has_no_operator_credentials_or_service_token():
    manifests = resources(b"source", "a" * 64, {"OPENAI_API_KEY": "test-key"}, ["192.0.2.10"])
    deployment = next(x for x in manifests if x["kind"] == "Deployment")
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    pod = deployment["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert not any("hostPath" in v or "secret" in v for v in pod["volumes"])
    for container in pod["containers"] + pod["initContainers"]:
        assert container["image"] == WEB_IMAGE
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert "--no-proxy-headers" in pod["containers"][0]["command"]
    config = next(x for x in manifests if x["kind"] == "ConfigMap" and x["metadata"]["name"] == "web-config")
    assert config["data"]["AUTOKAGGLE_PRIVATE_MODE"] == "1"
    assert config["data"]["AUTOKAGGLE_PUBLIC_BASE_URL"].startswith("https://")
    assert "OPENAI_API_KEY" not in config["data"]


def test_upload_storage_and_inbound_policy_are_bounded():
    manifests = resources(b"source", "a" * 64, {}, ["192.0.2.10"])
    claim = next(x for x in manifests if x["kind"] == "PersistentVolumeClaim")
    assert claim["spec"]["resources"]["requests"]["storage"] == "10Gi"
    policy = next(x for x in manifests if x["kind"] == "NetworkPolicy")["spec"]
    assert policy["ingress"] == [{"from": [{"ipBlock": {"cidr": "192.0.2.10/32"}}],
                                  "ports": [{"protocol": "TCP", "port": 8080}]}]
    assert set(policy["policyTypes"]) == {"Ingress", "Egress"}


def test_mail_secret_and_egress_only_apply_to_trusted_web(tmp_path):
    path = tmp_path / "mail.env"
    path.write_text('AUTOKAGGLE_SMTP_PASSWORD="test only pass word"\n')
    mail = mail_settings(path)
    manifests = resources(b"source", "a" * 64, {}, ["192.0.2.10"], mail=mail)
    secret = next(x for x in manifests if x["kind"] == "Secret" and x["metadata"]["name"] == "web-mail")
    assert secret["stringData"]["AUTOKAGGLE_SMTP_PASSWORD"] == "testonlypassword"
    policy = next(x for x in manifests if x["kind"] == "NetworkPolicy" and x["metadata"]["name"] == "web-mail")["spec"]
    assert policy["podSelector"] == {"matchLabels": {"app": "autokaggle-web"}}
    assert policy["egress"][0]["ports"] == [{"port": 465, "protocol": "TCP"}]
    configs = [x for x in manifests if x["kind"] == "ConfigMap"]
    assert all("testonlypassword" not in str(x) for x in configs)


def test_gmail_api_release_needs_no_smtp_rule_and_rejects_drive_tokens(tmp_path):
    path = tmp_path / "gmail.json"
    credential = {"type": "authorized_user", "scopes": ["https://www.googleapis.com/auth/gmail.send"],
                  "token_uri": "https://oauth2.googleapis.com/token", "expected_sender": "boldcoscientist@gmail.com",
                  "client_id": "test-client", "client_secret": "test-secret", "refresh_token": "test-refresh"}
    path.write_text(json.dumps(credential))
    mail = gmail_settings(path)
    manifests = resources(b"source", "a" * 64, {}, ["192.0.2.10"], mail=mail)
    assert not any(x["kind"] == "NetworkPolicy" and x["metadata"]["name"] == "web-mail" for x in manifests)
    secret = next(x for x in manifests if x["kind"] == "Secret" and x["metadata"]["name"] == "web-mail")
    assert secret["stringData"]["AUTOKAGGLE_GMAIL_REFRESH_TOKEN"] == "test-refresh"
    assert not any(k.startswith("AUTOKAGGLE_SMTP") for k in secret["stringData"])
    credential["scopes"] = ["https://www.googleapis.com/auth/drive.file"]
    path.write_text(json.dumps(credential))
    with pytest.raises(ValueError, match="send-only"):
        gmail_settings(path)
