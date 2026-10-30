import hashlib
import json
import os
from pathlib import Path
import subprocess
from contextlib import contextmanager

import pytest

from autokaggle.runner import CivoRunner, RunnerUnavailable, prepare_submission, validate_features
from autokaggle.runner import civo
from autokaggle.deploy import probe_cluster


@pytest.fixture(autouse=True)
def isolate_acceptance_records(tmp_path, monkeypatch):
    monkeypatch.setattr(civo, "_RUNTIME_EVIDENCE", tmp_path / "runtime.json")
    monkeypatch.setattr(civo, "_CONTROLLER_EVIDENCE", tmp_path / "controller.json")


def test_execution_is_disabled_even_if_environment_requests_it(monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_RUNNER_ENABLED", "1")
    runner = CivoRunner()
    assert runner.status()["enabled"] is False
    assert "not a fresh preflight" in runner.status()["evidence_kind"]
    with pytest.raises(RunnerUnavailable, match="Do not run.*locally"):
        runner.submit({"command": "arbitrary", "runtimeClassName": "runc"})


def test_forged_saved_report_cannot_enable_execution(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"cluster_id": civo.CLUSTER_ID, "code_execution_enabled": True, "blockers": []}))
    monkeypatch.setattr(civo, "_EVIDENCE", report)
    assert CivoRunner().status()["enabled"] is False
    with pytest.raises(RunnerUnavailable):
        CivoRunner().submit(None)


@pytest.mark.parametrize("run_id,source", [("../other", b"pass"), ("x" * 32, b"pass"), ("a" * 32, b""),
    ("a" * 32, b"\xff"), ("a" * 32, b"pass\x00"), ("a" * 32, b" " * 262145)])
def test_source_transport_rejects_invalid_input(run_id, source):
    with pytest.raises(ValueError):
        prepare_submission(run_id, source)


def test_source_is_hashed_without_execution(tmp_path):
    marker = tmp_path / "never-created"
    source = f"open({str(marker)!r}, 'w').write('bad')".encode()
    prepared = prepare_submission("a" * 32, source)
    assert prepared.source_sha256 == hashlib.sha256(source).hexdigest()
    assert not marker.exists()


def test_features_preserve_strings_and_reject_label_mounts():
    data = b"id,value\n001,NA\n002,\n"
    assert validate_features(data, expected_columns=["id", "value"], label_columns=["target"])["rows"] == 2
    with pytest.raises(ValueError, match="Private label"):
        validate_features(b"id,target\n001,1\n", expected_columns=["id", "target"], label_columns=["target"])
    with pytest.raises(ValueError, match="frozen"):
        validate_features(b"id,value,target\n001,NA,1\n", expected_columns=["id", "value"], label_columns=["target"])


@pytest.mark.parametrize("data", [b"id,value\n", b"id,value\n1,2,3\n", b"id,id\n1,2\n", b'id,value\n1,"broken\n', b"id,value\n1,\x00\n"])
def test_features_reject_invalid_csv(data):
    with pytest.raises(ValueError):
        validate_features(data, expected_columns=["id", "value"], label_columns=["target"])


def test_features_require_private_label_schema_and_bounded_rows(monkeypatch):
    with pytest.raises(ValueError, match="private label"):
        validate_features(b"id\n1\n", expected_columns=["id"], label_columns=[])
    monkeypatch.setattr(civo, "MAX_FEATURE_ROWS", 1)
    with pytest.raises(ValueError, match="row"):
        validate_features(b"id\n1\n2\n", expected_columns=["id"], label_columns=["target"])


def test_fixed_launch_contract_has_no_secret_or_host_access():
    source = prepare_submission("a" * 32, b"print('fixture')")
    job = civo.build_job_spec(source, operator_image=civo.APPROVED_IMAGE)
    spec = job["spec"]["template"]["spec"]
    assert spec["runtimeClassName"] == "autokaggle-gvisor"
    assert spec["automountServiceAccountToken"] is False
    assert all(spec[k] is False for k in ("hostPID", "hostIPC", "hostNetwork", "shareProcessNamespace"))
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert len(spec["containers"]) == 1 and "initContainers" not in spec
    container = spec["containers"][0]
    assert container["securityContext"] == {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
    assert container["command"] == ["/usr/local/bin/python", "-I", "-B", "/harness/entrypoint.py"]
    assert container["resources"]["limits"]["memory"] == "512Mi"
    assert job["spec"]["activeDeadlineSeconds"] == 120 and job["spec"]["backoffLimit"] == 0
    assert all("valueFrom" not in item for item in container["env"])
    assert all(not ({"secret", "hostPath", "projected"} & set(v)) for v in spec["volumes"])
    assert all(m["readOnly"] for m in container["volumeMounts"] if m["name"] in {"source", "features"})
    assert spec["volumes"][1]["persistentVolumeClaim"]["claimName"] == "run-" + "a" * 32 + "-features"
    assert "labels" not in str(spec["volumes"]).lower()


@pytest.mark.parametrize("image", ["python:latest", "runner@sha256:short", "python@sha256:" + "a" * 64 + ";sh", ""])
def test_job_rejects_unpinned_or_injected_image(image):
    with pytest.raises(ValueError, match="digest"):
        civo.build_job_spec(prepare_submission("a" * 32, b"pass"), operator_image=image)


def test_modified_prepared_source_cannot_reuse_hash():
    source = prepare_submission("a" * 32, b"pass")
    modified = civo.PreparedSubmission(source.run_id, "print('different')", source.source_sha256)
    with pytest.raises(ValueError, match="hash mismatch"):
        civo.build_job_spec(modified, operator_image="python@sha256:" + "a" * 64)


def test_temporary_kubeconfig_is_private_and_removed_on_failure(monkeypatch):
    paths = []
    def fake_run(args, **kwargs):
        assert args == ["civo", "kubernetes", "config", civo.CLUSTER_ID, "--region", "lon1"]
        assert "--save" not in args and "--switch" not in args
        kwargs["stdout"].write(b"private fixture")
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(probe_cluster.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="fixture failure"):
        with probe_cluster.private_kubeconfig() as path:
            paths.append(path)
            assert os.stat(path).st_mode & 0o777 == 0o600
            raise RuntimeError("fixture failure")
    assert not Path(paths[0]).exists()


def test_kubeconfig_error_does_not_expose_secret_stderr(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stderr=b"secret fixture")
    monkeypatch.setattr(probe_cluster.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError) as error:
        with probe_cluster.private_kubeconfig():
            pytest.fail("Must not yield on failure")
    assert "secret" not in str(error.value)


def test_preflight_does_not_equate_runtime_registration_with_approval():
    class ReadOnlyCluster:
        def json(self, *args):
            if args == ("get", "nodes"):
                return {"items": [{"metadata": {"name": "fixture-node"}, "status": {"nodeInfo": {
                    "osImage": "Alpine", "kernelVersion": "6", "containerRuntimeVersion": "containerd://2",
                    "kubeletVersion": "v1.35", "unexpected_secret": "must not be exported",
                }}}]}
            if args == ("get", "runtimeclasses"):
                return {"items": [{"metadata": {"name": "gvisor"}, "handler": "runsc"}]}
            if args[:2] == ("get", "configmap"):
                return {"data": {"enable-policy": "default", "unexpected_secret": "must not be exported"}}
            return {"items": []}

        def run(self, *args):
            assert args == ("get", "--raw", "/api/v1/nodes/fixture-node/proxy/configz")
            return json.dumps({"kubeletconfig": {"podPidsLimit": 256, "unexpected_secret": "must not be exported"}})

    result = probe_cluster.inspect_cluster(ReadOnlyCluster())
    assert result["code_execution_enabled"] is False
    assert result["nodes"][0]["pod_pids_limit"] == 256
    assert result["blockers"] == ["No approved sandbox execution path has passed the full acceptance suite."]
    assert "must not be exported" not in json.dumps(result)


def test_failed_kubelet_inspection_is_a_blocker():
    class InaccessibleCluster:
        def json(self, *args):
            if args == ("get", "nodes"):
                return {"items": [{"metadata": {"name": "fixture-node"}, "status": {"nodeInfo": {
                    "osImage": "Alpine", "kernelVersion": "6", "containerRuntimeVersion": "containerd://2", "kubeletVersion": "v1.35",
                }}}]}
            if args[:2] == ("get", "configmap"):
                raise RuntimeError("inaccessible")
            return {"items": []}

        def run(self, *args):
            raise RuntimeError("inaccessible")

    result = probe_cluster.inspect_cluster(InaccessibleCluster())
    assert result["code_execution_enabled"] is False
    assert any("PID" in blocker for blocker in result["blockers"])
    assert result["nodes"][0]["pod_pids_limit"] is None


def test_node_installer_help_is_read_only():
    script = Path(__file__).parents[1] / "deploy" / "install-gvisor-node.sh"
    result = subprocess.run(["sh", str(script), "--help"], capture_output=True, text=True, check=True)
    assert "does not restart" in result.stdout
    assert "saves private backups" in result.stdout
    subprocess.run(["sh", "-n", str(script)], check=True)


def test_status_reports_remote_environment_without_local_package_claims():
    status = CivoRunner().status()
    assert status["environment"] == {
        "python": None, "image": civo.APPROVED_IMAGE, "packages": {},
        "runtime": "gVisor release-20261019.0 (systrap, network=none)",
        "cpu": 1, "memory_mib": 512, "wall_seconds": 100, "cpu_seconds": 90,
        "job_deadline_seconds": 120, "gpus": 0,
    }


def test_saved_acceptance_still_requires_current_control_checks(monkeypatch):
    from autokaggle.runner import controller
    monkeypatch.setattr(CivoRunner, "_accepted_controller", lambda self: True)
    @contextmanager
    def config():
        yield "/private/fixture"
    monkeypatch.setattr(probe_cluster, "private_kubeconfig", config)
    monkeypatch.setattr(controller, "KubectlTransport", lambda path: path)
    def unavailable(kube):
        raise RunnerUnavailable("fixture control drift")
    monkeypatch.setattr(civo, "verified_runtime", unavailable)
    result = CivoRunner().status()
    assert result["enabled"] is False
    assert result["evidence_kind"] == "failed fresh preflight"


def test_runner_wrapper_uses_only_remote_controller(monkeypatch):
    from autokaggle.runner import controller
    monkeypatch.setattr(CivoRunner, "_accepted_controller", lambda self: True)
    calls = []
    @contextmanager
    def config():
        calls.append("config-open")
        try:
            yield "/private/fixture"
        finally:
            calls.append("config-cleaned")
    class Remote:
        def __init__(self, transport):
            assert transport == "/private/fixture"
        def submit(self, source, **kwargs):
            assert source == b"untrusted source"
            assert kwargs == {"features": b"features", "training": b"training",
                              "expected_columns": ["id", "x"], "label_columns": ["target"]}
            calls.append("remote-submit")
            return b"validated predictions"
    monkeypatch.setattr(probe_cluster, "private_kubeconfig", config)
    monkeypatch.setattr(controller, "KubectlTransport", lambda path: path)
    monkeypatch.setattr(controller, "CivoController", Remote)
    assert CivoRunner().submit(b"untrusted source", features=b"features", training=b"training",
                              expected_columns=["id", "x"], label_columns=["target"]) == b"validated predictions"
    assert calls == ["config-open", "remote-submit", "config-cleaned"]


@pytest.mark.parametrize("changed", ["entrypoint.py", "controller.py", "civo.py"])
def test_accepted_controller_binds_all_executable_contract_files(monkeypatch, changed):
    runtime = {"node_uid": "fixture-node", "boot_id": "fixture-boot"}
    monkeypatch.setattr(civo, "_runtime_receipt", lambda: runtime)
    folder = Path(civo.__file__).parent
    report = {"passed": True, "cleanup_confirmed": True, "cluster_id": civo.CLUSTER_ID,
              "image": civo.APPROVED_IMAGE, **runtime,
              "code_sha256": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                              for name in ("entrypoint.py", "controller.py", "civo.py")}}
    civo._CONTROLLER_EVIDENCE.write_text(json.dumps(report))
    assert CivoRunner()._accepted_controller() is True
    report["code_sha256"][changed] = "different"
    civo._CONTROLLER_EVIDENCE.write_text(json.dumps(report))
    assert CivoRunner()._accepted_controller() is False
