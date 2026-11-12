"""Deployment boundaries for the separate internal service."""
from autokaggle.deploy.lite_web import HOST, BASE_URL, resources, route_resources


def prepared():
    return resources(b"source", "a" * 64, {"OPENAI_API_KEY": "test-key"}, ["192.0.2.10"])


def test_lite_does_not_reuse_full_data_or_credentials():
    items = prepared()
    assert all(x["metadata"]["namespace"] == "autokaggle-web" for x in items)
    assert not any(x["metadata"]["name"] in {"web", "web-data", "web-config", "web-secrets"} for x in items)
    dep = next(x for x in items if x["kind"] == "Deployment")
    pod = dep["spec"]["template"]["spec"]
    assert dep["spec"]["selector"]["matchLabels"] == {"app": "autokaggle-lite"}
    assert dep["spec"]["replicas"] == 1
    assert dep["spec"]["strategy"]["type"] == "Recreate"
    assert [x["persistentVolumeClaim"]["claimName"] for x in pod["volumes"] if "persistentVolumeClaim" in x] == ["lite-data"]
    assert {x.get("secretRef", {}).get("name") for x in pod["containers"][0]["envFrom"]} == {None, "lite-secrets", "web-mail"}
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True
    claim = next(x for x in items if x["kind"] == "PersistentVolumeClaim")
    assert claim["spec"]["resources"]["requests"]["storage"] == "1Gi"


def test_lite_enables_private_access_consent_and_known_lab_member():
    config = next(x for x in prepared() if x["metadata"]["name"] == "lite-config")["data"]
    assert config["AUTOKAGGLE_PRIVATE_MODE"] == "1"
    assert config["AUTOKAGGLE_REQUIRE_STORAGE_CONSENT"] == "1"
    assert config["AUTOKAGGLE_LITE_MEMBERS"] == "boldcoscientist@gmail.com"
    assert config["AUTOKAGGLE_DEFAULT_INTERFACE"] == "lite"
    assert config["AUTOKAGGLE_WORKERS"] == "5"
    assert config["AUTOKAGGLE_ALLOWED_HOSTS"] == HOST
    assert config["AUTOKAGGLE_PUBLIC_BASE_URL"] == BASE_URL
    assert config["OPENAI_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert config["AUTOKAGGLE_MODEL"] == "openai/gpt-6.1-sol"
    assert "OPENAI_API_KEY" not in config


def test_lite_service_route_and_network_policy_select_only_lite():
    items = prepared()
    assert next(x for x in items if x["kind"] == "Service")["spec"]["selector"] == {"app": "autokaggle-lite"}
    policy = next(x for x in items if x["kind"] == "NetworkPolicy")["spec"]
    assert policy["podSelector"] == {"matchLabels": {"app": "autokaggle-lite"}}
    assert policy["ingress"] == [{"from": [{"ipBlock": {"cidr": "192.0.2.10/32"}}], "ports": [{"protocol": "TCP", "port": 8080}]}]
    assert set(policy["policyTypes"]) == {"Ingress", "Egress"}
    assert policy["egress"][1]["ports"] == [{"port": 443, "protocol": "TCP"}]
    route = route_resources()[0]
    assert route["metadata"]["name"] == "lite"
    assert route["spec"]["rules"][0]["host"] == HOST
    assert route["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]["name"] == "lite"
    assert route["spec"]["tls"] == [{"hosts": [HOST], "secretName": "autokaggle-lite-tls"}]


def test_model_secret_supports_lite_and_existing_model_clients(tmp_path, monkeypatch):
    from autokaggle.deploy import lite_web
    model = tmp_path / "model.env"
    model.write_text("OPENROUTER_API_KEY=test-only-key\n")
    monkeypatch.setattr(lite_web, "PRIVATE_ENV", tmp_path / "private.env")
    monkeypatch.setattr(lite_web, "GITHUB_ENV", tmp_path / "absent-github.env")
    private = lite_web.private_settings(model)
    assert "AUTOKAGGLE_LITE_GITHUB_TOKEN" not in private
    assert private["OPENROUTER_API_KEY"] == "test-only-key"
    assert private["OPENAI_API_KEY"] == "test-only-key"
    items = lite_web.resources(b"source", "a" * 64, private, ["192.0.2.10"])
    secret = next(item for item in items if item["kind"] == "Secret")
    assert secret["metadata"]["name"] == "lite-secrets"
    assert secret["stringData"]["OPENROUTER_API_KEY"] == "test-only-key"
    deployment = next(item for item in items if item["kind"] == "Deployment")
    refs = deployment["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    assert {"secretRef": {"name": "lite-secrets"}} in refs
    assert all("test-only-key" not in str(item) for item in items if item["kind"] == "ConfigMap")


def test_github_token_enters_only_the_secret_and_the_owner_only_the_config(tmp_path, monkeypatch):
    from autokaggle.deploy import lite_web
    model = tmp_path / "model.env"
    model.write_text("OPENROUTER_API_KEY=test-only-key\n")
    token = "github_pat_" + "A1b2C3d4_" * 9
    github = tmp_path / "github.env"
    github.write_text("# private\nAUTOKAGGLE_LITE_GITHUB_TOKEN=" + token + "\n")
    monkeypatch.setattr(lite_web, "PRIVATE_ENV", tmp_path / "private.env")
    monkeypatch.setattr(lite_web, "GITHUB_ENV", github)
    private = lite_web.private_settings(model)
    assert private["AUTOKAGGLE_LITE_GITHUB_TOKEN"] == token
    assert token not in (tmp_path / "private.env").read_text()
    items = lite_web.resources(b"source", "a" * 64, private, ["192.0.2.10"], github_owner="bold-lab-ai")
    assert next(x for x in items if x["kind"] == "Secret")["stringData"]["AUTOKAGGLE_LITE_GITHUB_TOKEN"] == token
    config = next(x for x in items if x["metadata"]["name"] == "lite-config")["data"]
    assert config["AUTOKAGGLE_LITE_GITHUB_OWNER"] == "bold-lab-ai"
    assert all(token not in str(x) for x in items if x["kind"] != "Secret")
    # The owner is part of the restart hash. Without an owner the setting is absent and publishing stays off.
    hashed = lambda x: next(i for i in x if i["kind"] == "Deployment")["spec"]["template"]["metadata"]["annotations"]["autokaggle/settings-sha256"]
    plain = lite_web.resources(b"source", "a" * 64, private, ["192.0.2.10"])
    assert hashed(plain) != hashed(items)
    assert "AUTOKAGGLE_LITE_GITHUB_OWNER" not in next(x for x in plain if x["metadata"]["name"] == "lite-config")["data"]
    import pytest
    with pytest.raises(ValueError):
        lite_web.resources(b"source", "a" * 64, private, ["192.0.2.10"], github_owner="not a name")
    github.write_text("AUTOKAGGLE_LITE_GITHUB_TOKEN=two words\n")
    with pytest.raises(ValueError):
        lite_web.github_settings()


def test_hosted_source_bundle_starts_without_the_build_image_and_pins_the_git_library(tmp_path):
    import io, os, subprocess, sys, tarfile
    from autokaggle.deploy import web
    source, _ = web.bundle()
    with tarfile.open(fileobj=io.BytesIO(source)) as archive:
        names = archive.getnames()
        archive.extractall(tmp_path / "app", filter="data")
    assert "autokaggle/lite_publish.py" in names and "autokaggle/deploy/lite-build.Dockerfile" not in names
    lock = (tmp_path / "app/autokaggle/deploy/web-requirements.lock").read_text().split()
    assert "dulwich==1.2.20" in lock and "urllib3==2.8.0" in lock
    code = ("import json, pathlib, sys\nfrom fastapi.testclient import TestClient\nfrom autokaggle import lite_build\nfrom autokaggle.app import create_app\n"
            "app = create_app(pathlib.Path(sys.argv[1]))\nruntime = lite_build.default_runtime()\n"
            "with TestClient(app) as client:\n    page = client.get('/lite').status_code\n"
            "print(json.dumps({'kind': runtime.kind, 'available': runtime.available(), 'page': page}))\napp.state.pool.shutdown(wait=True)\n")
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "app"), "AUTOKAGGLE_PRIVATE_MODE": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-c", code, str(tmp_path / "data")], cwd=tmp_path / "app", env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    import json
    started = json.loads(done.stdout.strip().splitlines()[-1])
    assert started == {"kind": "docker", "available": [False, "Evaluator builds are not installed on this server."], "page": 200}


def test_deploy_keeps_the_github_token_off_the_cluster_when_publishing_is_off():
    import inspect
    from autokaggle.deploy import lite_web
    body = inspect.getsource(lite_web.main)
    assert body.index('private.pop("AUTOKAGGLE_LITE_GITHUB_TOKEN", None)') < body.index("for item in resources(")
