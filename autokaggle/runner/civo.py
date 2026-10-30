"""Fixed isolated code runner with saved acceptance and fresh control checks.

No environment flag, runtime name, or participant-supplied report can enable
execution. A changed worker requires new runtime acceptance evidence.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re

CLUSTER_ID = "ecc962fa-2f4c-4a3f-96c4-179af273fb7a"
NAMESPACE = "autokaggle-runs"
RUNTIME_CLASS = "autokaggle-gvisor"
MAX_CODE_BYTES = 256 * 1024
MAX_FEATURE_BYTES = 50 * 1024 * 1024
MAX_FEATURE_ROWS = 100_000
MAX_FEATURE_COLUMNS = 200
_EVIDENCE = Path(__file__).resolve().parent.parent / "deploy" / "cluster-inspection.json"
_RUNTIME_EVIDENCE = Path(__file__).resolve().parent.parent / "deploy" / "runtime-verification.json"
_CONTROLLER_EVIDENCE = Path(__file__).resolve().parent.parent / "deploy" / "controller-verification.json"
APPROVED_IMAGE = "docker.io/library/python@sha256:5789aa194f757888f41fa3d48e14b6feaa1b57c0af0b56fcb1372d6474d3bff0"
_BLOCKERS = (
    "The strong sandbox runtime has not passed acceptance tests on the AutoKaggle cluster.",
    "Per-pod PID limits and all network paths need verified enforcement on each runner node.",
    "Trusted staging, bounded result collection, and private scoring are not connected to an approved runner.",
)


class RunnerUnavailable(RuntimeError):
    """Code execution is disabled; the caller must not fall back to local execution."""


def _runtime_receipt():
    try:
        receipt = json.loads(_RUNTIME_EVIDENCE.read_text())
    except (OSError, ValueError):
        return None
    if (not isinstance(receipt, dict) or receipt.get("passed") is not True or receipt.get("cluster_id") != CLUSTER_ID
            or receipt.get("release") != "20261019.0" or receipt.get("image") != APPROVED_IMAGE or receipt.get("cleanup_confirmed") is not True
            or any(not isinstance(receipt.get(key), str) or not receipt[key] for key in ("node_uid", "boot_id", "node", "checked_at"))):
        return None
    return receipt


def verified_runtime(kube) -> dict:
    """Read live controls before staging; a passing saved test alone is insufficient."""
    receipt = _runtime_receipt()
    if receipt is None:
        raise RunnerUnavailable("The sandbox has no complete passing acceptance record.")
    try:
        node = kube.json("get", "node", receipt["node"])
        if (node["metadata"]["uid"] != receipt["node_uid"] or node["status"]["nodeInfo"]["bootID"] != receipt["boot_id"]
                or node["metadata"].get("labels", {}).get("autokaggle.openphil.org/sandbox") != "gvisor-verified"
                or not any(c["type"] == "Ready" and c["status"] == "True" for c in node["status"]["conditions"])):
            raise RunnerUnavailable("The tested execution node changed or is not Ready; repeat runtime verification.")
        selected = kube.json("get", "nodes", "-l", "autokaggle.openphil.org/sandbox=gvisor-verified")["items"]
        if len(selected) != 1 or selected[0]["metadata"]["uid"] != receipt["node_uid"]:
            raise RunnerUnavailable("The runtime can schedule onto a node without a matching acceptance record.")
        runtime = kube.json("get", "runtimeclass", RUNTIME_CLASS)
        if runtime.get("handler") != "autokaggle-runsc" or runtime.get("scheduling", {}).get("nodeSelector") != {"autokaggle.openphil.org/sandbox": "gvisor-verified"}:
            raise RunnerUnavailable("The registered sandbox runtime does not match the tested contract.")
        namespace = kube.json("get", "namespace", NAMESPACE)
        if namespace["metadata"].get("labels", {}).get("pod-security.kubernetes.io/enforce") != "restricted":
            raise RunnerUnavailable("Restricted pod security is not enforced for execution.")
        policy = kube.json("get", "ciliumnetworkpolicy", "explicit-deny-all", "-n", NAMESPACE)["spec"]
        if (policy.get("endpointSelector") != {} or policy.get("ingressDeny") != [{"fromEntities": ["all"]}]
                or policy.get("egressDeny") != [{"toEntities": ["all"]}]):
            raise RunnerUnavailable("The required network deny policy is missing or changed.")
        baseline = kube.json("get", "networkpolicy", "deny-all", "-n", NAMESPACE)["spec"]
        if baseline.get("podSelector") != {} or set(baseline.get("policyTypes", [])) != {"Ingress", "Egress"} or baseline.get("ingress") or baseline.get("egress"):
            raise RunnerUnavailable("The namespace network policy is missing or changed.")
        service = kube.json("get", "serviceaccount", "runner-no-access", "-n", NAMESPACE)
        if service.get("automountServiceAccountToken") is not False:
            raise RunnerUnavailable("The worker service account can receive credentials.")
        config = json.loads(kube.run("get", "--raw", f"/api/v1/nodes/{receipt['node']}/proxy/configz"))
        if config.get("kubeletconfig", {}).get("podPidsLimit") != 256:
            raise RunnerUnavailable("The tested node process limit changed.")
        storage = kube.json("get", "storageclass", "civo-volume")
        if storage.get("provisioner") != "csi.civo.com" or storage.get("reclaimPolicy") != "Delete":
            raise RunnerUnavailable("The isolated run storage contract changed.")
        for resource, key in (("validatingadmissionpolicy", "admission_sha256"),
                              ("validatingadmissionpolicybinding", "admission_binding_sha256")):
            current = kube.json("get", resource, "autokaggle-fixed-runner")
            digest = hashlib.sha256(json.dumps(current["spec"], sort_keys=True).encode()).hexdigest()
            if digest != receipt.get(key):
                raise RunnerUnavailable("The fixed runner admission control is missing or changed.")
        if current["spec"].get("validationActions") != ["Deny"]:
            raise RunnerUnavailable("The fixed runner admission control is not enforced.")
    except RunnerUnavailable:
        raise
    except (RuntimeError, KeyError, ValueError, TypeError):
        raise RunnerUnavailable("A required live execution control could not be verified.") from None
    return {"enabled": True, "cluster_id": CLUSTER_ID, "node": receipt["node"], "node_uid": receipt["node_uid"],
        "verified_at": receipt["checked_at"], "image": APPROVED_IMAGE, "evidence_kind": "passing runtime fixtures plus fresh control checks"}


@dataclass(frozen=True)
class PreparedSubmission:
    run_id: str
    source: str
    source_sha256: str


def prepare_submission(run_id: str, source: bytes) -> PreparedSubmission:
    """Validate the transport format without executing or storing the program."""
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Run ID must contain 32 lowercase hexadecimal characters.")
    if not isinstance(source, bytes) or not 1 <= len(source) <= MAX_CODE_BYTES:
        raise ValueError("Submit one Python source file of at most 256 KiB.")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Python source must use UTF-8.") from None
    if "\x00" in text or not text.strip():
        raise ValueError("Python source must be nonempty text without null bytes.")
    return PreparedSubmission(run_id, text, hashlib.sha256(source).hexdigest())


def validate_features(data: bytes, *, expected_columns: list[str], label_columns: list[str]) -> dict:
    """Check a feature-only CSV against a trusted frozen task schema.

    Both column lists must come from the organizer's frozen task, never the
    uploaded program. Training data is a different artifact and is not checked
    here. This check cannot establish whether a feature is a scientific proxy.
    """
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_FEATURE_BYTES:
        raise ValueError("Hidden input features must be a CSV of at most 50 MiB.")
    if (not isinstance(expected_columns, list) or not 1 <= len(expected_columns) <= MAX_FEATURE_COLUMNS
            or any(not isinstance(x, str) or not x or x != x.strip() for x in expected_columns)
            or len(set(expected_columns)) != len(expected_columns)):
        raise ValueError("Expected feature columns must be unique, nonempty names.")
    if not isinstance(label_columns, list) or not label_columns or any(not isinstance(x, str) or not x for x in label_columns):
        raise ValueError("The trusted task must identify its private label columns.")
    if set(expected_columns) & set(label_columns):
        raise ValueError("Private label columns cannot enter the prediction worker.")
    try:
        text = data.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("Null bytes are not accepted in feature CSV files.")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader)
        if header != expected_columns:
            raise ValueError("Hidden input columns do not match the frozen feature schema.")
        count = 0
        for row in reader:
            if len(row) != len(header):
                raise ValueError("Hidden input rows must have the expected number of columns.")
            count += 1
            if count > MAX_FEATURE_ROWS:
                raise ValueError("Hidden inputs exceed the 100,000-row runner bound.")
        if not count:
            raise ValueError("Hidden input CSV has no data rows.")
    except (UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise ValueError("Hidden inputs are not a valid UTF-8 CSV.") from error
    return {"sha256": hashlib.sha256(data).hexdigest(), "rows": count, "columns": list(header), "bytes": len(data)}


def build_job_spec(submission: PreparedSubmission, *, operator_image: str) -> dict:
    """Create a fixed Job contract; this function does not submit it.

    operator_image is an operator-owned image reference, not an API parameter.
    Its digest must match the reviewed Python image. The staging service creates
    immutable source/harness resources and separate per-run data volumes.
    """
    if not isinstance(submission, PreparedSubmission):
        raise ValueError("A prepared source submission is required.")
    prepared = prepare_submission(submission.run_id, submission.source.encode("utf-8"))
    if prepared.source_sha256 != submission.source_sha256:
        raise ValueError("Submission hash mismatch.")
    if operator_image != APPROVED_IMAGE:
        raise ValueError("The image digest must match the fixed reviewed runtime image.")
    name = "run-" + submission.run_id
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "namespace": NAMESPACE, "labels": {"app": "autokaggle-runner", "run-id": submission.run_id}},
        "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 120, "ttlSecondsAfterFinished": 600,
            "template": {"metadata": {"labels": {"app": "autokaggle-runner", "run-id": submission.run_id}}, "spec": {
                "runtimeClassName": RUNTIME_CLASS, "nodeSelector": {"autokaggle.openphil.org/sandbox": "gvisor-verified"},
                "automountServiceAccountToken": False, "serviceAccountName": "runner-no-access", "enableServiceLinks": False,
                "hostNetwork": False, "hostPID": False, "hostIPC": False, "shareProcessNamespace": False,
                "restartPolicy": "Never", "terminationGracePeriodSeconds": 5,
                "securityContext": {"runAsNonRoot": True, "runAsUser": 65532, "runAsGroup": 65532, "fsGroup": 65532,
                    "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [{"name": "prediction", "image": operator_image, "imagePullPolicy": "IfNotPresent",
                    "command": ["/usr/local/bin/python", "-I", "-B", "/harness/entrypoint.py"],
                    "workingDir": "/scratch", "terminationMessagePolicy": "File", "terminationMessagePath": "/scratch/termination",
                    "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                    "resources": {"requests": {"cpu": "250m", "memory": "256Mi", "ephemeral-storage": "64Mi"},
                        "limits": {"cpu": "1", "memory": "512Mi", "ephemeral-storage": "256Mi"}},
                    "env": [{"name": key, "value": value} for key, value in {"HOME": "/scratch", "TMPDIR": "/scratch", "OMP_NUM_THREADS": "1",
                        "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}.items()],
                    "volumeMounts": [{"name": "source", "mountPath": "/submission", "readOnly": True},
                        {"name": "features", "mountPath": "/input", "readOnly": True},
                        {"name": "scratch", "mountPath": "/scratch"}, {"name": "output", "mountPath": "/output"},
                        {"name": "harness", "mountPath": "/harness", "readOnly": True}],
                }],
                "volumes": [{"name": "source", "configMap": {"name": name + "-source", "defaultMode": 292}},
                    {"name": "features", "persistentVolumeClaim": {"claimName": name + "-features", "readOnly": True}},
                    {"name": "scratch", "emptyDir": {"medium": "Memory", "sizeLimit": "128Mi"}},
                    {"name": "output", "persistentVolumeClaim": {"claimName": name + "-output"}},
                    {"name": "harness", "configMap": {"name": name + "-harness", "defaultMode": 292}}],
            }}}}


class CivoRunner:
    """Application interface; all submitted Python runs in the remote sandbox."""

    def _accepted_controller(self):
        runtime = _runtime_receipt()
        try:
            report = json.loads(_CONTROLLER_EVIDENCE.read_text())
            if (runtime is None or not isinstance(report, dict) or report.get("passed") is not True or report.get("cleanup_confirmed") is not True
                    or report.get("cluster_id") != CLUSTER_ID or report.get("image") != APPROVED_IMAGE
                    or report.get("node_uid") != runtime["node_uid"] or report.get("boot_id") != runtime["boot_id"]):
                return False
            # A changed harness/controller must pass the integration fixtures again.
            for name in ("entrypoint.py", "controller.py", "civo.py"):
                digest = hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                if report.get("code_sha256", {}).get(name) != digest:
                    return False
            return True
        except (OSError, ValueError, TypeError):
            return False

    def _environment(self):
        receipt = _runtime_receipt() or {}
        access = receipt.get("access") if isinstance(receipt.get("access"), dict) else {}
        return {"python": access.get("python"), "image": APPROVED_IMAGE,
                "packages": {}, "runtime": "gVisor release-20261019.0 (systrap, network=none)",
                "cpu": 1, "memory_mib": 512, "wall_seconds": 100, "cpu_seconds": 90,
                "job_deadline_seconds": 120, "gpus": 0}

    def status(self) -> dict:
        evidence = None
        try:
            candidate = json.loads(_EVIDENCE.read_text())
            if isinstance(candidate, dict) and candidate.get("cluster_id") == CLUSTER_ID:
                evidence = candidate
        except (OSError, ValueError):
            pass
        result = {"enabled": False, "cluster_id": CLUSTER_ID, "region": "lon1", "environment": self._environment(),
            "state": "blocked", "message": "Code execution is disabled until the isolated runner passes its acceptance checks.",
            "blockers": list(_BLOCKERS), "evidence_kind": "saved inspection; not a fresh preflight", "evidence": evidence}
        if not self._accepted_controller():
            return result
        try:
            from ..deploy.probe_cluster import private_kubeconfig
            from .controller import KubectlTransport
            with private_kubeconfig() as config:
                verified = verified_runtime(KubectlTransport(config))
            result.update(verified)
            result.update(state="ready", message="Isolated code execution is available.", blockers=[])
        except Exception:
            result.update(message="The sandbox is unavailable because a current control check did not pass.",
                          blockers=["Current runtime controls could not be verified."], evidence_kind="failed fresh preflight")
        return result

    def submit(self, source: bytes, *, features: bytes | None = None, training: bytes | None = None,
               expected_columns: list[str] | None = None, label_columns: list[str] | None = None) -> bytes:
        if not self._accepted_controller():
            raise RunnerUnavailable("Code execution is disabled: the AutoKaggle sandbox has not passed acceptance checks. Do not run the submission locally.")
        from ..deploy.probe_cluster import private_kubeconfig
        from .controller import CivoController, KubectlTransport
        with private_kubeconfig() as config:
            return CivoController(KubectlTransport(config)).submit(source, features=features, training=training,
                                                                  expected_columns=expected_columns, label_columns=label_columns)

    def preflight(self) -> dict:
        """Perform a new read-only inspection; saved acceptance is also required."""
        from ..deploy.probe_cluster import Kubectl, inspect_cluster, private_kubeconfig
        with private_kubeconfig() as config:
            inspection = inspect_cluster(Kubectl(config))
        result = self.status()
        result.update(evidence_kind="fresh read-only preflight; no sandbox execution test", evidence=inspection)
        return result
