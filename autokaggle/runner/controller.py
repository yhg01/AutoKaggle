"""Bounded transport between the trusted scorer and an approved Civo worker.

This module does not approve a runtime. ``submit`` requires the operator-owned
``civo.verified_runtime`` check before any write and again before worker launch.
No submitted program is executed on the controller host. Hidden answer data is
not an argument, a volume, a ConfigMap, or a returned artifact.

The only result is a structurally validated prediction CSV for the trusted
application scorer. That scorer must still check metric-specific value domains.
Never return these bytes, worker files, or worker logs to a participant.
"""
from __future__ import annotations

import copy
import csv
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time
import uuid

from . import civo

OPERATOR_IMAGE = "docker.io/library/python@sha256:5789aa194f757888f41fa3d48e14b6feaa1b57c0af0b56fcb1372d6474d3bff0"
STORAGE_CLASS = "civo-volume"
MAX_PREDICTION_BYTES = 5_000_000
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ERROR_BYTES = 64 * 1024
ID_COLUMN = "_autokaggle_id"
OWNER_ANNOTATION = "autokaggle.openphil.org/controller-owner"
LOCK_NAME = "autokaggle-controller-active"
_HARNESS = Path(__file__).with_name("entrypoint.py")
HELPER_READY_SECONDS = 300
HELPER_LIFETIME_SECONDS = 600
_HOLD = "import time; time.sleep(600)"

# These are fixed transport programs, not participant-provided shell commands.
# stdin carries file bytes; argv carries only trusted length and SHA-256 values.
_STAGE = '''import hashlib, os, sys
path = "__FIXED_PATH__"
expected_size = int(sys.argv[1])
expected_hash = sys.argv[2]
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o440)
size = 0
digest = hashlib.sha256()
try:
    with os.fdopen(fd, "wb") as output:
        while True:
            chunk = sys.stdin.buffer.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > expected_size or size > 52428800:
                raise ValueError()
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if size != expected_size or digest.hexdigest() != expected_hash:
        raise ValueError()
except BaseException:
    try:
        os.unlink(path)
    except OSError:
        pass
    raise SystemExit(1) from None
'''
_STAGE_FEATURES = _STAGE.replace("__FIXED_PATH__", "/input/test_features.csv")
_STAGE_TRAINING = _STAGE.replace("__FIXED_PATH__", "/input/train.csv")
_COLLECT = '''import os, stat, sys
try:
    fd = os.open("/output/predictions.csv", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 1 <= info.st_size <= 5000000:
            raise ValueError()
        data = source.read(5000001)
        if len(data) != info.st_size or len(data) > 5000000:
            raise ValueError()
    sys.stdout.buffer.write(data)
except BaseException:
    raise SystemExit(1) from None
'''


class ControllerFailure(RuntimeError):
    """A fixed, public-safe failure; never include process output in the message."""


class CleanupIncomplete(ControllerFailure):
    """The operator must inspect the retained lock before another run."""


class RunBusy(ControllerFailure):
    """A namespace-wide run lock already exists or could not be acquired."""


def _bounded_process(argv, *, input_bytes=None, timeout=45, stdout_limit=MAX_JSON_BYTES):
    """Drain both streams with fixed memory and time bounds. Never use a shell."""
    if input_bytes is not None and (not isinstance(input_bytes, bytes) or len(input_bytes) > civo.MAX_FEATURE_BYTES):
        raise ValueError("The transport input exceeds its byte limit.")
    if not 0 < timeout <= 180 or not 0 < stdout_limit <= MAX_PREDICTION_BYTES:
        raise ValueError("The transport bounds are invalid.")
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        raise ControllerFailure("The cluster transport could not start.") from None
    selector = selectors.DefaultSelector()
    output = bytearray()
    errors = 0
    sent = 0
    completed = False
    deadline = time.monotonic() + timeout
    try:
        for stream, name in ((process.stdout, "out"), (process.stderr, "err")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        if process.stdin:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "in")
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ControllerFailure("The cluster operation exceeded its time limit.")
            for key, _ in selector.select(min(0.2, remaining)):
                stream = key.fileobj
                if key.data == "in":
                    try:
                        amount = os.write(stream.fileno(), input_bytes[sent:sent + 16384]) if sent < len(input_bytes) else 0
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        amount = 0
                    if amount:
                        sent += amount
                    else:
                        selector.unregister(stream)
                        stream.close()
                    continue
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    continue
                if key.data == "out":
                    if len(output) + len(chunk) > stdout_limit:
                        raise ControllerFailure("The cluster operation exceeded its output limit.")
                    output.extend(chunk)
                else:
                    errors += len(chunk)
                    if errors > MAX_ERROR_BYTES:
                        raise ControllerFailure("The cluster operation exceeded its diagnostic limit.")
        try:
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise ControllerFailure("The cluster operation exceeded its time limit.") from None
        if code or (input_bytes is not None and sent != len(input_bytes)):
            raise ControllerFailure("The cluster operation failed.")
        completed = True
        return bytes(output)
    except (OSError, ValueError):
        raise ControllerFailure("The cluster transport failed.") from None
    finally:
        cleanup_failed = False
        if not completed or process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                cleanup_failed = True
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cleanup_failed = True
        selector.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()
        if cleanup_failed:
            raise ControllerFailure("The cluster transport could not be stopped.") from None


class KubectlTransport:
    """Use an operator-created private kubeconfig without changing user context.

    The path and all kubectl arguments are trusted controller configuration.
    They must not be accepted as participant request fields.
    """

    def __init__(self, kubeconfig):
        path = Path(kubeconfig)
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("The controller requires a private, regular kubeconfig file.")
        self.kubeconfig = str(path)

    def run_bytes(self, *args, stdin=None, timeout=45, stdout_limit=MAX_JSON_BYTES):
        return _bounded_process(["kubectl", "--kubeconfig", self.kubeconfig, "--request-timeout=60s", *args],
                                input_bytes=stdin, timeout=timeout, stdout_limit=stdout_limit)

    def run(self, *args, document=None, timeout=45):
        encoded = json.dumps(document, ensure_ascii=False).encode("utf-8") if document is not None else None
        try:
            return self.run_bytes(*args, stdin=encoded, timeout=timeout).decode("utf-8")
        except UnicodeDecodeError:
            raise ControllerFailure("The cluster returned an invalid text response.") from None

    def json(self, *args, document=None, timeout=45):
        text = self.run(*args, "-o", "json", document=document, timeout=timeout)
        try:
            return json.loads(text) if text.strip() else None
        except ValueError:
            raise ControllerFailure("The cluster returned an invalid structured response.") from None


@dataclass(frozen=True)
class FrozenTask:
    feature_columns: tuple[str, ...]
    label_columns: tuple[str, ...]


@dataclass(frozen=True)
class PreparedRun:
    submission: civo.PreparedSubmission = field(repr=False)
    features: bytes = field(repr=False)
    training: bytes | None = field(repr=False)
    input_ids: tuple[str, ...] = field(repr=False)
    owner: str


def _csv_rows(data, *, maximum, message):
    if not isinstance(data, bytes) or not 1 <= len(data) <= maximum:
        raise ValueError(message)
    try:
        text = data.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError(message)
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader)
        if not header or len(header) != len(set(header)):
            raise ValueError(message)
        yield header
        for number, row in enumerate(reader, 1):
            if number > civo.MAX_FEATURE_ROWS or len(row) != len(header):
                raise ValueError(message)
            yield row
    except (UnicodeDecodeError, csv.Error, StopIteration):
        raise ValueError(message) from None


def prepare_run(source, *, features, training, task):
    """Inspect trusted data and source bytes without executing any program.

    The trusted application selects the training subset. Training can omit the
    generated evaluation ID column. If it contains IDs, they must be disjoint.
    """
    if not isinstance(task, FrozenTask):
        raise ValueError("A frozen task schema is required.")
    prepared = civo.prepare_submission(uuid.uuid4().hex, source)
    civo.validate_features(features, expected_columns=list(task.feature_columns), label_columns=list(task.label_columns))
    if ID_COLUMN not in task.feature_columns:
        raise ValueError("The frozen features must include the input ID column.")
    rows = iter(_csv_rows(features, maximum=civo.MAX_FEATURE_BYTES, message="The feature CSV is invalid."))
    header = next(rows)
    index = header.index(ID_COLUMN)
    ids = tuple(row[index] for row in rows)
    if any(not value or value != value.strip() or len(value) > 256 for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Feature IDs must be unique, nonempty, and bounded.")
    if training is not None:
        rows = iter(_csv_rows(training, maximum=civo.MAX_FEATURE_BYTES, message="The training CSV is invalid or exceeds 50 MiB."))
        header = next(rows)
        with_ids = set(task.feature_columns) | set(task.label_columns)
        without_ids = with_ids - {ID_COLUMN}
        if set(header) not in (with_ids, without_ids):
            raise ValueError("Training columns must match the frozen feature and training-label schema.")
        index = header.index(ID_COLUMN) if ID_COLUMN in header else None
        seen = set()
        held_out = set(ids)
        count = 0
        for row in rows:
            count += 1
            if index is None:
                continue
            value = row[index]
            if not value or value != value.strip() or len(value) > 256 or value in seen or value in held_out:
                raise ValueError("Training IDs must be unique and separate from evaluation IDs.")
            seen.add(value)
        if not count:
            raise ValueError("The training CSV has no rows.")
    return PreparedRun(prepared, features, training, ids, uuid.uuid4().hex)


def validate_predictions(data, *, input_ids):
    """Return canonical CSV only after row, ID, shape, and byte validation.

    Metric-specific checks remain in the trusted scorer, which has the labels.
    """
    ids = tuple(input_ids)
    if not ids or len(ids) > civo.MAX_FEATURE_ROWS or len(ids) != len(set(ids)):
        raise ValueError("The trusted prediction ID schema is invalid.")
    rows = iter(_csv_rows(data, maximum=MAX_PREDICTION_BYTES, message="The prediction CSV is invalid or exceeds its byte limit."))
    if next(rows) != [ID_COLUMN, "prediction"]:
        raise ValueError("The prediction CSV must have the published columns.")
    expected = set(ids)
    predictions = {}
    for row in rows:
        identifier, value = row
        if identifier not in expected or identifier in predictions or not value.strip() or len(value) > 4096:
            raise ValueError("The prediction CSV has invalid IDs or values.")
        predictions[identifier] = value
    if set(predictions) != expected:
        raise ValueError("The prediction CSV must contain every input ID exactly once.")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([ID_COLUMN, "prediction"])
    writer.writerows((identifier, predictions[identifier]) for identifier in ids)
    result = output.getvalue().encode("utf-8")
    if len(result) > MAX_PREDICTION_BYTES:
        raise ValueError("The canonical prediction CSV exceeds its byte limit.")
    return result


def require_verified_runtime(kube):
    verifier = getattr(civo, "verified_runtime", None)
    if not callable(verifier):
        raise civo.RunnerUnavailable("Code execution is disabled: runtime acceptance is unavailable. Do not run the submission locally.")
    try:
        evidence = verifier(kube)
    except Exception:
        raise civo.RunnerUnavailable("Code execution is disabled: fresh runtime verification did not pass. Do not run the submission locally.") from None
    if not isinstance(evidence, dict) or evidence.get("enabled") is not True or evidence.get("cluster_id") != civo.CLUSTER_ID:
        raise civo.RunnerUnavailable("Code execution is disabled: verified runtime evidence is required. Do not run the submission locally.")


def _metadata(run, name):
    return {"name": name, "namespace": civo.NAMESPACE, "labels": {"app": "autokaggle-runner", "run-id": run.submission.run_id},
            "annotations": {OWNER_ANNOTATION: run.owner}}


def build_resources(run):
    """Create the fixed staging plan. This function performs no cluster writes."""
    name = "run-" + run.submission.run_id
    job = civo.build_job_spec(run.submission, operator_image=OPERATOR_IMAGE)
    spec = job["spec"]["template"]["spec"]
    volumes = {value["name"]: value for value in spec["volumes"]}
    if (volumes.get("output", {}).get("persistentVolumeClaim", {}).get("claimName") != name + "-output"
            or volumes.get("harness", {}).get("configMap", {}).get("name") != name + "-harness"
            or spec["containers"][0]["command"] != ["/usr/local/bin/python", "-I", "-B", "/harness/entrypoint.py"]):
        raise civo.RunnerUnavailable("Code execution is disabled: the fixed job storage contract is not installed.")
    harness = _HARNESS.read_bytes()
    if not 1 <= len(harness) <= civo.MAX_CODE_BYTES:
        raise civo.RunnerUnavailable("The trusted runner harness has an invalid size.")
    source = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": _metadata(run, name + "-source"), "immutable": True, "data": {"main.py": run.submission.source}}
    entrypoint = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": _metadata(run, name + "-harness"), "immutable": True, "data": {"entrypoint.py": harness.decode("utf-8")}}
    claims = [{"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": _metadata(run, name + "-" + suffix),
               "spec": {"accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem", "storageClassName": STORAGE_CLASS,
                        "resources": {"requests": {"storage": "1Gi"}}}} for suffix in ("features", "output")]
    job["metadata"] = _metadata(run, name)
    job["spec"]["template"]["metadata"].setdefault("annotations", {})[OWNER_ANNOTATION] = run.owner
    helpers = []
    for role, volume_name, readonly in (("stage", "features", False), ("collect", "output", True)):
        helper = copy.deepcopy(spec)
        helper["activeDeadlineSeconds"] = HELPER_LIFETIME_SECONDS
        helper["containers"][0]["command"] = ["/usr/local/bin/python", "-I", "-B", "-c", _HOLD]
        helper["containers"][0]["volumeMounts"] = [{"name": volume_name, "mountPath": "/input" if role == "stage" else "/output", "readOnly": readonly},
                                                   {"name": "scratch", "mountPath": "/scratch"}]
        helper["volumes"] = [{"name": volume_name, "persistentVolumeClaim": {"claimName": name + "-" + volume_name, "readOnly": readonly}},
                             {"name": "scratch", "emptyDir": {"medium": "Memory", "sizeLimit": "32Mi"}}]
        if role == "stage":
            # Bind and attach both new volumes before the program's execution
            # deadline starts. The fixed staging scripts only write /input.
            helper["containers"][0]["volumeMounts"].append({"name": "output", "mountPath": "/output"})
            helper["volumes"].append({"name": "output", "persistentVolumeClaim": {"claimName": name + "-output"}})
        helpers.append({"apiVersion": "v1", "kind": "Pod", "metadata": _metadata(run, name + "-" + role), "spec": helper})
    lock = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": _metadata(run, LOCK_NAME), "immutable": True, "data": {"run_id": run.submission.run_id}}
    return {"lock": lock, "source": source, "harness": entrypoint, "claims": claims, "job": job, "stage": helpers[0], "collect": helpers[1]}


class CivoController:
    """One bounded run, serialized by an atomic namespace ConfigMap lock."""

    def __init__(self, kube):
        self.kube = kube

    def _owned(self, resource, run):
        found = self.kube.json("get", resource["kind"], resource["metadata"]["name"], "-n", civo.NAMESPACE, "--ignore-not-found")
        if not found:
            return None
        metadata = found.get("metadata", {})
        if (metadata.get("annotations", {}).get(OWNER_ANNOTATION) != run.owner
                or metadata.get("name") != resource["metadata"]["name"] or metadata.get("namespace") != civo.NAMESPACE):
            raise CleanupIncomplete("A run resource has different ownership. The operator must inspect the run lock.")
        return found

    def _delete(self, resource, run):
        found = self._owned(resource, run)
        if not found:
            return
        volume = None
        if resource["kind"] == "PersistentVolumeClaim":
            volume = found.get("spec", {}).get("volumeName")
            if volume:
                pv = self.kube.json("get", "persistentvolume", volume)
                claim = pv.get("spec", {}).get("claimRef", {}) if pv else {}
                if (claim.get("uid") != found["metadata"].get("uid") or claim.get("namespace") != civo.NAMESPACE
                        or claim.get("name") != found["metadata"]["name"] or pv.get("spec", {}).get("persistentVolumeReclaimPolicy") != "Delete"):
                    raise CleanupIncomplete("The run storage reclaim contract changed. The operator must inspect the run lock.")
        self.kube.run("delete", resource["kind"], resource["metadata"]["name"], "-n", civo.NAMESPACE,
                      "--ignore-not-found", "--cascade=foreground", "--wait=true", "--timeout=60s", timeout=70)
        if volume:
            self.kube.run("wait", "--for=delete", "persistentvolume/" + volume, "--timeout=60s", timeout=70)

    def _create(self, resource, attempted):
        # Record intent before the request: an interrupted response may conceal
        # a successful create. Ownership is checked before every cleanup delete.
        attempted.append(resource)
        self.kube.run("create", "-f", "-", document=resource)

    def _ready(self, resource):
        name = resource["metadata"]["name"]
        deadline = time.monotonic() + HELPER_READY_SECONDS
        while time.monotonic() < deadline:
            wait_seconds = max(1, min(20, int(deadline - time.monotonic())))
            try:
                self.kube.run("wait", "-n", civo.NAMESPACE, "--for=condition=Ready", "pod/" + name,
                              "--timeout=" + str(wait_seconds) + "s", timeout=wait_seconds + 10)
                return
            except ControllerFailure:
                pod = self.kube.json("get", "pod", name, "-n", civo.NAMESPACE)
                if not pod or pod.get("status", {}).get("phase") in {"Succeeded", "Failed"}:
                    raise ControllerFailure("The run helper stopped before it became ready.") from None
        raise ControllerFailure("The run helper exceeded its storage readiness deadline.")

    def _wait_job(self, resource):
        deadline = time.monotonic() + 145
        while time.monotonic() < deadline:
            job = self.kube.json("get", "job", resource["metadata"]["name"], "-n", civo.NAMESPACE)
            conditions = {item.get("type"): item.get("status") for item in job.get("status", {}).get("conditions", [])}
            if conditions.get("Complete") == "True" and job.get("status", {}).get("succeeded") == 1:
                return
            if conditions.get("Failed") == "True" or job.get("status", {}).get("failed", 0):
                raise ControllerFailure("The code run did not finish successfully.")
            time.sleep(1)
        raise ControllerFailure("The code run exceeded its completion deadline.")

    def submit(self, source: bytes, *, features: bytes, training: bytes | None = None,
               expected_columns: list[str], label_columns: list[str]) -> bytes:
        require_verified_runtime(self.kube)
        storage = self.kube.json("get", "storageclass", STORAGE_CLASS)
        if (not storage or storage.get("provisioner") != "csi.civo.com" or storage.get("reclaimPolicy") != "Delete"
                or storage.get("volumeBindingMode") != "WaitForFirstConsumer"):
            raise civo.RunnerUnavailable("Code execution is disabled: the approved storage contract is unavailable.")
        run = prepare_run(source, features=features, training=training,
                          task=FrozenTask(tuple(expected_columns), tuple(label_columns)))
        resources = build_resources(run)
        lock = resources["lock"]
        try:
            self.kube.run("create", "-f", "-", document=lock)
        except Exception:
            # An existing lock belongs to another run. An uncertain create may
            # have made our lock; remove it only if its ownership can be proved.
            try:
                found = self._owned(lock, run)
                if found:
                    self._delete(lock, run)
            except Exception:
                pass
            raise RunBusy("The runner is busy or the run lock could not be acquired.") from None
        attempted = []
        cleanup_failed = False
        try:
            for resource in (resources["source"], resources["harness"], *resources["claims"], resources["stage"]):
                self._create(resource, attempted)
            self._ready(resources["stage"])
            for script, data in ((_STAGE_FEATURES, run.features), (_STAGE_TRAINING, run.training)):
                if data is None:
                    continue
                self.kube.run_bytes("exec", "-i", "-n", civo.NAMESPACE, resources["stage"]["metadata"]["name"], "-c", "prediction", "--",
                                    "/usr/local/bin/python", "-I", "-B", "-c", script, str(len(data)), hashlib.sha256(data).hexdigest(),
                                    stdin=data, timeout=90, stdout_limit=1024)
            self._delete(resources["stage"], run)
            require_verified_runtime(self.kube)
            self._create(resources["job"], attempted)
            self._wait_job(resources["job"])
            # No worker can keep writing while the collector reads the output.
            self._delete(resources["job"], run)
            self._create(resources["collect"], attempted)
            self._ready(resources["collect"])
            output = self.kube.run_bytes("exec", "-n", civo.NAMESPACE, resources["collect"]["metadata"]["name"], "-c", "prediction", "--",
                                         "/usr/local/bin/python", "-I", "-B", "-c", _COLLECT, timeout=45, stdout_limit=MAX_PREDICTION_BYTES)
            try:
                return validate_predictions(output, input_ids=run.input_ids)
            except ValueError:
                raise ControllerFailure("The worker did not produce a valid prediction CSV.") from None
        except (civo.RunnerUnavailable, ControllerFailure):
            raise
        except Exception:
            raise ControllerFailure("The code run could not be completed.") from None
        finally:
            for resource in reversed(attempted):
                try:
                    self._delete(resource, run)
                except Exception:
                    cleanup_failed = True
            if not cleanup_failed:
                try:
                    self._delete(lock, run)
                except Exception:
                    cleanup_failed = True
            if cleanup_failed:
                raise CleanupIncomplete("Run cleanup was not confirmed. The run lock is retained; operator review is required.") from None
