"""Controller tests use fake cluster responses and fixed transport fixtures.

No participant program is run locally and no real cluster is contacted.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from autokaggle.runner import civo
from autokaggle.runner import controller as ctrl


FEATURES = b"_autokaggle_id,value\nvalidation-1,3\nvalidation-2,4\n"
TRAINING = b"value,target\n1,8\n2,9\n"
PREDICTIONS = b"_autokaggle_id,prediction\nvalidation-2,9\nvalidation-1,8\n"
CANONICAL = b"_autokaggle_id,prediction\nvalidation-1,8\nvalidation-2,9\n"
TASK = ctrl.FrozenTask((ctrl.ID_COLUMN, "value"), ("target",))


def prepare(*, source=b"pass", features=FEATURES, training=TRAINING):
    return ctrl.prepare_run(source, features=features, training=training, task=TASK)


def submit(kube, **kwargs):
    values = dict(features=FEATURES, training=TRAINING,
                  expected_columns=list(TASK.feature_columns), label_columns=list(TASK.label_columns))
    values.update(kwargs)
    return ctrl.CivoController(kube).submit(b"pass", **values)


class FakeKube:
    """Record the wire contract and model the relevant Kubernetes state."""

    def __init__(self):
        self.resources = {}
        self.calls = []
        self.predictions = PREDICTIONS
        self.storage = {"provisioner": "csi.civo.com", "reclaimPolicy": "Delete", "volumeBindingMode": "WaitForFirstConsumer"}
        self.fail_create_suffix = None
        self.fail_delete_suffix = None
        self.fail_stage = False
        self.fail_collect = False
        self.job_failed = False
        self.runtime_calls = 0
        self.runtime_fail_at = None

    @staticmethod
    def key(kind, name):
        return kind.lower(), name

    def verify(self, _):
        self.runtime_calls += 1
        if self.runtime_calls == self.runtime_fail_at:
            raise civo.RunnerUnavailable("private fixture diagnostic")
        return {"enabled": True, "cluster_id": civo.CLUSTER_ID}

    def json(self, *args, **kwargs):
        self.calls.append(("json", args, kwargs))
        assert args[0] == "get"
        if args[1] == "storageclass":
            return copy.deepcopy(self.storage)
        found = copy.deepcopy(self.resources.get(self.key(args[1], args[2])))
        if found and args[1].lower() == "job":
            found["status"] = ({"failed": 1, "conditions": [{"type": "Failed", "status": "True"}]} if self.job_failed
                               else {"succeeded": 1, "conditions": [{"type": "Complete", "status": "True"}]})
        return found

    def run(self, *args, document=None, **kwargs):
        self.calls.append(("run", args, {"document": copy.deepcopy(document), **kwargs}))
        if args[0] == "create":
            resource = copy.deepcopy(document)
            kind, name = resource["kind"], resource["metadata"]["name"]
            key = self.key(kind, name)
            if key in self.resources:
                raise ctrl.ControllerFailure("already exists")
            resource["metadata"]["uid"] = "uid-" + name
            if kind == "PersistentVolumeClaim":
                volume = "pv-" + name
                resource["spec"]["volumeName"] = volume
                self.resources[self.key("persistentvolume", volume)] = {
                    "spec": {"persistentVolumeReclaimPolicy": "Delete", "claimRef": {
                        "uid": resource["metadata"]["uid"], "name": name, "namespace": civo.NAMESPACE}}}
            self.resources[key] = resource
            if self.fail_create_suffix and name.endswith(self.fail_create_suffix):
                raise ctrl.ControllerFailure("response lost after successful create")
        elif args[0] == "delete":
            kind, name = args[1:3]
            if self.fail_delete_suffix and name.endswith(self.fail_delete_suffix):
                raise ctrl.ControllerFailure("delete fixture failure")
            resource = self.resources.pop(self.key(kind, name), None)
            if resource and kind == "PersistentVolumeClaim":
                self.resources.pop(self.key("persistentvolume", resource["spec"]["volumeName"]), None)
        elif args[0] == "wait":
            if "--for=delete" in args:
                target = next(arg for arg in args if arg.startswith("persistentvolume/"))
                assert self.key(*target.split("/", 1)) not in self.resources
        else:
            raise AssertionError(args)
        return ""

    def run_bytes(self, *args, stdin=None, **kwargs):
        self.calls.append(("bytes", args, {"stdin": stdin, **kwargs}))
        assert args[0] == "exec" and "--" in args
        if stdin is not None:
            if self.fail_stage:
                raise ctrl.ControllerFailure("staging fixture failure")
            assert args[-2:] == (str(len(stdin)), hashlib.sha256(stdin).hexdigest())
            return b""
        if self.fail_collect:
            raise ctrl.ControllerFailure("collection fixture failure")
        return self.predictions


@pytest.fixture
def kube(monkeypatch):
    instance = FakeKube()
    monkeypatch.setattr(civo, "verified_runtime", instance.verify)
    return instance


def test_prepare_keeps_source_as_bytes_without_execution(tmp_path):
    marker = tmp_path / "must-not-exist"
    source = f"open({str(marker)!r}, 'w').write('bad')".encode()
    prepared = prepare(source=source)
    assert prepared.submission.source == source.decode()
    assert prepared.input_ids == ("validation-1", "validation-2")
    assert prepared.training == TRAINING
    assert not marker.exists()
    assert "must-not-exist" not in repr(prepared)


def test_training_can_omit_generated_ids_or_be_absent():
    assert prepare().training == TRAINING
    assert prepare(training=None).training is None
    with_ids = b"_autokaggle_id,value,target\ntrain-1,1,8\ntrain-2,2,9\n"
    assert prepare(training=with_ids).training == with_ids


@pytest.mark.parametrize("training", [
    b"value,target\n", b"value,wrong\n1,8\n", b"value,target,secret\n1,8,9\n",
    b"_autokaggle_id,value,target\nvalidation-1,1,8\n",
    b"_autokaggle_id,value,target\ntrain-1,1,8\ntrain-1,2,9\n",
    b"_autokaggle_id,value,target\n,1,8\n", b"value,target\n1,\xff\n",
    b"value,target\n1,\x00\n", b"value,target\n1,2,3\n",
])
def test_training_rejects_invalid_schema_and_overlapping_ids(training):
    with pytest.raises(ValueError):
        prepare(training=training)


@pytest.mark.parametrize("features", [
    b"_autokaggle_id,value\n,1\n", b"_autokaggle_id,value\n x,1\n",
    b"_autokaggle_id,value\nx,1\nx,2\n", b"_autokaggle_id,value,target\nx,1,2\n",
])
def test_features_reject_invalid_ids_and_label_columns(features):
    with pytest.raises(ValueError):
        prepare(features=features)


def test_training_and_source_byte_limits(monkeypatch):
    monkeypatch.setattr(civo, "MAX_FEATURE_BYTES", len(FEATURES))
    with pytest.raises(ValueError):
        prepare(training=b" " * (len(FEATURES) + 1))
    with pytest.raises(ValueError):
        prepare(source=b"x" * (civo.MAX_CODE_BYTES + 1))


def test_predictions_are_canonical_in_trusted_id_order():
    assert ctrl.validate_predictions(PREDICTIONS, input_ids=("validation-1", "validation-2")) == CANONICAL


@pytest.mark.parametrize("data", [
    b"_autokaggle_id,prediction\nvalidation-1,8\n",
    b"_autokaggle_id,prediction\nvalidation-1,8\nvalidation-1,9\n",
    b"_autokaggle_id,prediction\nvalidation-1,8\nextra,9\n",
    b"_autokaggle_id,target\nvalidation-1,8\nvalidation-2,9\n",
    b"_autokaggle_id,prediction\nvalidation-1, \nvalidation-2,9\n",
    b"_autokaggle_id,prediction\nvalidation-1,8,extra\nvalidation-2,9\n",
    b"_autokaggle_id,prediction\nvalidation-1,\xff\nvalidation-2,9\n",
    b"_autokaggle_id,prediction\nvalidation-1,\x00\nvalidation-2,9\n",
    b"_autokaggle_id,prediction\nvalidation-1," + b"x" * 4097 + b"\nvalidation-2,9\n",
])
def test_predictions_reject_bad_shape_ids_and_values(data):
    with pytest.raises(ValueError):
        ctrl.validate_predictions(data, input_ids=("validation-1", "validation-2"))


def test_prediction_size_bound(monkeypatch):
    monkeypatch.setattr(ctrl, "MAX_PREDICTION_BYTES", len(PREDICTIONS) - 1)
    with pytest.raises(ValueError):
        ctrl.validate_predictions(PREDICTIONS, input_ids=("validation-1", "validation-2"))


def test_resource_contract_has_fixed_limits_and_only_needed_mounts():
    resources = ctrl.build_resources(prepare())
    assert len(resources["claims"]) == 2
    for claim in resources["claims"]:
        assert claim["spec"]["storageClassName"] == "civo-volume"
        assert claim["spec"]["resources"]["requests"]["storage"] == "1Gi"
    assert resources["source"]["immutable"] is True
    assert resources["harness"]["immutable"] is True
    assert resources["source"]["data"] == {"main.py": "pass"}
    for role, expected in (("stage", {"features", "output", "scratch"}), ("collect", {"output", "scratch"})):
        spec = resources[role]["spec"]
        container = spec["containers"][0]
        assert container["image"] == ctrl.OPERATOR_IMAGE
        assert spec["runtimeClassName"] == civo.RUNTIME_CLASS
        assert spec["automountServiceAccountToken"] is False
        assert spec["activeDeadlineSeconds"] == 600
        assert {volume["name"] for volume in spec["volumes"]} == expected
        assert container["resources"]["limits"]["memory"] == "512Mi"
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert resources["collect"]["spec"]["containers"][0]["volumeMounts"][0]["readOnly"] is True
    assert any(mount["mountPath"] == "/output" for mount in resources["stage"]["spec"]["containers"][0]["volumeMounts"])
    assert "/output" not in ctrl._STAGE_FEATURES and "/output" not in ctrl._STAGE_TRAINING
    assert resources["job"]["spec"]["activeDeadlineSeconds"] == 120
    assert "validation-1" not in json.dumps(resources)
    assert "value,target" not in json.dumps(resources)


@pytest.mark.parametrize("evidence", [None, {}, {"enabled": True, "cluster_id": "other"}, {"enabled": 1, "cluster_id": civo.CLUSTER_ID}])
def test_runtime_evidence_must_pass_before_any_cluster_write(monkeypatch, evidence):
    fake = FakeKube()
    monkeypatch.setattr(civo, "verified_runtime", lambda _: evidence)
    with pytest.raises(civo.RunnerUnavailable):
        submit(fake)
    assert fake.calls == []


def test_missing_runtime_verifier_is_closed(monkeypatch):
    monkeypatch.delattr(civo, "verified_runtime")
    fake = FakeKube()
    with pytest.raises(civo.RunnerUnavailable):
        submit(fake)
    assert fake.calls == []


def test_storage_contract_checked_before_mutation(kube):
    kube.storage["reclaimPolicy"] = "Retain"
    with pytest.raises(civo.RunnerUnavailable):
        submit(kube)
    assert all(kind == "json" for kind, _, _ in kube.calls)


def test_full_run_stages_only_declared_inputs_collects_after_worker_deletion_and_cleans(kube):
    assert submit(kube) == CANONICAL
    assert kube.runtime_calls == 2
    assert kube.resources == {}
    transfers = [(args, options) for kind, args, options in kube.calls if kind == "bytes"]
    assert [options["stdin"] for _, options in transfers] == [FEATURES, TRAINING, None]
    assert transfers[-1][1]["stdout_limit"] == 5_000_000
    calls = [(kind, args) for kind, args, _ in kube.calls]
    delete_job = next(i for i, (kind, args) in enumerate(calls) if kind == "run" and args[:2] == ("delete", "Job"))
    collect = next(i for i, (kind, args) in enumerate(calls) if kind == "bytes" and "-i" not in args)
    assert delete_job < collect
    assert not any(arg in {"logs", "cp", "sh", "bash"} for _, args, _ in kube.calls for arg in args)


def test_optional_training_is_not_staged(kube):
    assert submit(kube, training=None) == CANONICAL
    assert [options["stdin"] for kind, _, options in kube.calls if kind == "bytes"] == [FEATURES, None]


def test_helper_readiness_retries_bounded_waits_during_slow_attachment(kube, monkeypatch):
    helper = ctrl.build_resources(prepare())["stage"]
    attempts = []
    def wait(*args, **kwargs):
        attempts.append((args, kwargs))
        if len(attempts) < 3:
            raise ctrl.ControllerFailure("wait timed out")
    monkeypatch.setattr(kube, "run", wait)
    monkeypatch.setattr(kube, "json", lambda *args: {"status": {"phase": "Pending"}})
    ctrl.CivoController(kube)._ready(helper)
    assert len(attempts) == 3
    assert all("--timeout=20s" in args and options["timeout"] == 30 for args, options in attempts)


def test_helper_readiness_stops_on_failed_pod(kube, monkeypatch):
    def wait(*args, **kwargs):
        raise ctrl.ControllerFailure("wait timed out")
    monkeypatch.setattr(kube, "run", wait)
    monkeypatch.setattr(kube, "json", lambda *args: {"status": {"phase": "Failed"}})
    with pytest.raises(ctrl.ControllerFailure, match="stopped before"):
        ctrl.CivoController(kube)._ready(ctrl.build_resources(prepare())["stage"])


def test_helper_readiness_has_an_overall_deadline(kube, monkeypatch):
    clock = {"now": 0}
    def wait(*args, **kwargs):
        clock["now"] += 20
        raise ctrl.ControllerFailure("wait timed out")
    monkeypatch.setattr(ctrl.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(kube, "run", wait)
    monkeypatch.setattr(kube, "json", lambda *args: {"status": {"phase": "Pending"}})
    with pytest.raises(ctrl.ControllerFailure, match="storage readiness deadline"):
        ctrl.CivoController(kube)._ready(ctrl.build_resources(prepare())["stage"])
    assert clock["now"] == 300


@pytest.mark.parametrize("failure", ["fail_stage", "job_failed", "fail_collect"])
def test_failures_clean_every_run_resource(kube, failure):
    setattr(kube, failure, True)
    with pytest.raises(ctrl.ControllerFailure):
        submit(kube)
    assert kube.resources == {}


def test_invalid_worker_output_is_sanitized_and_cleaned(kube):
    kube.predictions = b"private-worker-output"
    with pytest.raises(ctrl.ControllerFailure) as error:
        submit(kube)
    assert str(error.value) == "The worker did not produce a valid prediction CSV."
    assert kube.resources == {}


def test_runtime_rechecked_after_staging_before_program_launch(kube):
    kube.runtime_fail_at = 2
    with pytest.raises(civo.RunnerUnavailable):
        submit(kube)
    assert kube.resources == {}
    assert not any(options.get("document", {}).get("kind") == "Job"
                   for kind, _, options in kube.calls if kind == "run" and options.get("document"))


@pytest.mark.parametrize("suffix", ["-source", "-features", "-stage", "-collect", ctrl.LOCK_NAME])
def test_ambiguous_create_is_cleaned_only_with_matching_ownership(kube, suffix):
    kube.fail_create_suffix = suffix
    with pytest.raises(ctrl.ControllerFailure):
        submit(kube)
    assert kube.resources == {}


def test_foreign_lock_is_not_deleted(kube):
    foreign = {"kind": "ConfigMap", "metadata": {"name": ctrl.LOCK_NAME, "namespace": civo.NAMESPACE,
               "annotations": {ctrl.OWNER_ANNOTATION: "someone-else"}}}
    kube.resources[kube.key("ConfigMap", ctrl.LOCK_NAME)] = foreign
    with pytest.raises(ctrl.RunBusy):
        submit(kube)
    assert list(kube.resources.values()) == [foreign]
    assert not any(args[0] == "delete" for kind, args, _ in kube.calls if kind == "run")


def test_cleanup_failure_retains_lock_and_blocks_result(kube):
    kube.fail_delete_suffix = "-output"
    with pytest.raises(ctrl.CleanupIncomplete):
        submit(kube)
    assert kube.key("ConfigMap", ctrl.LOCK_NAME) in kube.resources
    assert len([item for item in kube.resources.values() if item.get("kind") == "PersistentVolumeClaim"]) == 1
    assert not any(item.get("kind") in {"Job", "Pod"} for item in kube.resources.values())


def test_kubectl_transport_uses_argv_and_private_configuration(tmp_path, monkeypatch):
    path = tmp_path / "private config"
    path.write_text("fixture")
    path.chmod(0o600)
    calls = []
    def process(argv, **options):
        calls.append((argv, options))
        return b'{"ready": true}'
    monkeypatch.setattr(ctrl, "_bounded_process", process)
    kube = ctrl.KubectlTransport(path)
    assert kube.json("get", "node", "fixed") == {"ready": True}
    assert calls[0][0] == ["kubectl", "--kubeconfig", str(path), "--request-timeout=60s", "get", "node", "fixed", "-o", "json"]
    path.chmod(0o644)
    with pytest.raises(ValueError):
        ctrl.KubectlTransport(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        ctrl.KubectlTransport(link)


def test_bounded_transport_copies_fixed_fixture_with_backpressure():
    data = b"fixed transport fixture\n" * 4000
    result = ctrl._bounded_process([sys.executable, "-I", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                                   input_bytes=data, timeout=5, stdout_limit=len(data))
    assert result == data


@pytest.mark.parametrize("program,options,message", [
    ("print('x' * 1000)", {"stdout_limit": 100}, "output limit"),
    ("import sys; sys.stderr.write('private fixture' * 10000)", {}, "diagnostic limit"),
    ("import time; time.sleep(10)", {"timeout": 0.1}, "time limit"),
    ("import sys; sys.stderr.write('private fixture'); sys.exit(1)", {}, "operation failed"),
])
def test_bounded_transport_has_safe_errors(program, options, message):
    with pytest.raises(ctrl.ControllerFailure, match=message) as error:
        ctrl._bounded_process([sys.executable, "-I", "-c", program], **options)
    assert "private fixture" not in str(error.value)


def test_missing_transport_binary_has_safe_error():
    with pytest.raises(ctrl.ControllerFailure, match="could not start"):
        ctrl._bounded_process(["/no/such/autokaggle-fixed-fixture"])
