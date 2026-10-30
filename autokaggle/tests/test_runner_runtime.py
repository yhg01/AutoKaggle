"""Fresh runtime verification tests. All cluster reads use fixed fake data."""
import copy
import hashlib
import json

import pytest

from autokaggle.runner import civo


def digest(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


class RuntimeControls:
    def __init__(self):
        self.calls = []
        self.node = {"metadata": {"uid": "tested-node-uid", "labels": {"autokaggle.openphil.org/sandbox": "gvisor-verified"}},
                     "status": {"nodeInfo": {"bootID": "tested-boot-id"}, "conditions": [{"type": "Ready", "status": "True"}]}}
        self.selected = {"items": [copy.deepcopy(self.node)]}
        self.runtime = {"handler": "autokaggle-runsc", "scheduling": {"nodeSelector": {"autokaggle.openphil.org/sandbox": "gvisor-verified"}}}
        self.namespace = {"metadata": {"labels": {"pod-security.kubernetes.io/enforce": "restricted"}}}
        self.cilium = {"spec": {"endpointSelector": {}, "ingressDeny": [{"fromEntities": ["all"]}], "egressDeny": [{"toEntities": ["all"]}]}}
        self.network = {"spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": []}}
        self.service = {"automountServiceAccountToken": False}
        self.config = {"kubeletconfig": {"podPidsLimit": 256}}
        self.storage = {"provisioner": "csi.civo.com", "reclaimPolicy": "Delete", "volumeBindingMode": "WaitForFirstConsumer"}
        # The tested property is an exact match to the operator's saved spec
        # hash. The live acceptance test verifies the actual deployed policy.
        self.admission = {"spec": {"failurePolicy": "Fail", "matchConstraints": {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": civo.NAMESPACE}},
            "resourceRules": [{"apiGroups": [""], "apiVersions": ["v1"], "operations": ["CREATE", "UPDATE"], "resources": ["pods", "pods/ephemeralcontainers"]}]},
            "validations": [{"expression": "object.spec.containers.all(c, c.image == '" + civo.APPROVED_IMAGE + "')",
                             "message": "The reviewed Python image digest is required."}]}}
        self.binding = {"spec": {"policyName": "autokaggle-fixed-runner", "validationActions": ["Deny"]}}
        self.raise_resource = None
        self.missing_resource = None

    def receipt(self):
        return {"passed": True, "cluster_id": civo.CLUSTER_ID, "release": "20261019.0", "cleanup_confirmed": True,
                "image": civo.APPROVED_IMAGE,
                "node": "tested-node", "node_uid": "tested-node-uid", "boot_id": "tested-boot-id", "checked_at": "2026-10-27T12:00:00+00:00",
                "admission_sha256": digest(self.admission["spec"]), "admission_binding_sha256": digest(self.binding["spec"])}

    def json(self, *args):
        self.calls.append(args)
        assert args[0] == "get", "Runtime verification must be read-only."
        resource = args[1]
        if resource == self.raise_resource:
            raise RuntimeError("private fake cluster diagnostic")
        if resource == self.missing_resource:
            return {}
        mapping = {"node": self.node, "nodes": self.selected, "runtimeclass": self.runtime, "namespace": self.namespace,
                   "ciliumnetworkpolicy": self.cilium, "networkpolicy": self.network, "serviceaccount": self.service,
                   "storageclass": self.storage, "validatingadmissionpolicy": self.admission, "validatingadmissionpolicybinding": self.binding}
        assert resource in mapping
        return copy.deepcopy(mapping[resource])

    def run(self, *args):
        self.calls.append(args)
        assert args == ("get", "--raw", "/api/v1/nodes/tested-node/proxy/configz")
        return json.dumps(self.config)


@pytest.fixture
def controls(tmp_path, monkeypatch):
    fixture = RuntimeControls()
    path = tmp_path / "runtime-verification.json"
    path.write_text(json.dumps(fixture.receipt()))
    monkeypatch.setattr(civo, "_RUNTIME_EVIDENCE", path)
    fixture.path = path
    return fixture


def test_complete_receipt_and_matching_live_controls_enable_only_the_fixed_cluster(controls):
    result = civo.verified_runtime(controls)
    assert result["enabled"] is True
    assert result["cluster_id"] == civo.CLUSTER_ID
    assert result["node_uid"] == "tested-node-uid"
    assert result["image"] == civo.APPROVED_IMAGE
    assert result["verified_at"] == "2026-10-27T12:00:00+00:00"
    assert len(controls.calls) == 11
    assert all(call[0] == "get" for call in controls.calls)


@pytest.mark.parametrize("field", ["passed", "cluster_id", "release", "image", "cleanup_confirmed", "node", "node_uid", "boot_id", "checked_at", "admission_sha256", "admission_binding_sha256"])
def test_incomplete_receipt_fails_closed(controls, field):
    receipt = controls.receipt()
    del receipt[field]
    controls.path.write_text(json.dumps(receipt))
    with pytest.raises(civo.RunnerUnavailable):
        civo.verified_runtime(controls)


@pytest.mark.parametrize("field,value", [("passed", False), ("passed", 1), ("cleanup_confirmed", False), ("cleanup_confirmed", 1),
    ("cluster_id", "other-cluster"), ("release", "other-release"), ("image", "python:latest"), ("admission_sha256", "different"), ("admission_binding_sha256", "different")])
def test_invalid_receipt_values_fail_closed(controls, field, value):
    receipt = controls.receipt()
    receipt[field] = value
    controls.path.write_text(json.dumps(receipt))
    with pytest.raises(civo.RunnerUnavailable):
        civo.verified_runtime(controls)


@pytest.mark.parametrize("text", ["", "invalid-json", "null", "[]", "true", '"invalid-object"'])
def test_malformed_receipt_fails_closed(controls, text):
    controls.path.write_text(text)
    with pytest.raises(civo.RunnerUnavailable):
        civo.verified_runtime(controls)
    assert controls.calls == []


def test_missing_receipt_fails_before_cluster_reads(controls):
    controls.path.unlink()
    with pytest.raises(civo.RunnerUnavailable):
        civo.verified_runtime(controls)
    assert controls.calls == []


DRIFTS = [
    ("node", ("metadata", "uid"), "replacement-node"),
    ("node", ("status", "nodeInfo", "bootID"), "new-boot"),
    ("node", ("metadata", "labels"), {}),
    ("node", ("status", "conditions"), []),
    ("node", ("status", "conditions"), [{"type": "Ready", "status": "False"}]),
    ("selected", ("items",), []),
    ("selected", ("items",), [{"metadata": {"uid": "different-node"}}]),
    ("selected", ("items",), [{"metadata": {"uid": "tested-node-uid"}}, {"metadata": {"uid": "extra-node"}}]),
    ("runtime", ("handler",), "runc"),
    ("runtime", ("scheduling", "nodeSelector"), {}),
    ("runtime", ("scheduling", "nodeSelector"), {"autokaggle.openphil.org/sandbox": "gvisor-verified", "extra": "selector"}),
    ("namespace", ("metadata", "labels"), {}),
    ("namespace", ("metadata", "labels", "pod-security.kubernetes.io/enforce"), "baseline"),
    ("cilium", ("spec", "endpointSelector"), {"matchLabels": {"other": "pod"}}),
    ("cilium", ("spec", "ingressDeny"), []),
    ("cilium", ("spec", "egressDeny"), []),
    ("cilium", ("spec", "egressDeny"), [{"toEntities": ["world"]}]),
    ("network", ("spec", "podSelector"), {"matchLabels": {"other": "pod"}}),
    ("network", ("spec", "policyTypes"), ["Ingress"]),
    ("network", ("spec", "ingress"), [{}]),
    ("network", ("spec", "egress"), [{}]),
    ("service", ("automountServiceAccountToken",), True),
    ("service", ("automountServiceAccountToken",), None),
    ("service", ("automountServiceAccountToken",), 0),
    ("config", ("kubeletconfig", "podPidsLimit"), -1),
    ("config", ("kubeletconfig", "podPidsLimit"), 0),
    ("config", ("kubeletconfig", "podPidsLimit"), 257),
    ("storage", ("provisioner",), "other-driver"),
    ("storage", ("reclaimPolicy",), "Retain"),
    ("admission", ("spec", "failurePolicy"), "Ignore"),
    ("admission", ("spec", "validations"), []),
    ("binding", ("spec", "policyName"), "other-policy"),
    ("binding", ("spec", "validationActions"), ["Warn"]),
]


@pytest.mark.parametrize("field,path,value", DRIFTS, ids=[field + "-" + "-".join(path) + "-" + str(i) for i, (field, path, _) in enumerate(DRIFTS)])
def test_live_control_drift_fails_closed(controls, field, path, value):
    target = getattr(controls, field)
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(civo.RunnerUnavailable):
        civo.verified_runtime(controls)


RESOURCES = ["node", "nodes", "runtimeclass", "namespace", "ciliumnetworkpolicy", "networkpolicy", "serviceaccount",
             "storageclass", "validatingadmissionpolicy", "validatingadmissionpolicybinding"]


@pytest.mark.parametrize("resource", RESOURCES)
def test_missing_live_control_fails_closed(controls, resource):
    controls.missing_resource = resource
    with pytest.raises(civo.RunnerUnavailable):
        civo.verified_runtime(controls)


@pytest.mark.parametrize("resource", RESOURCES)
def test_cluster_read_error_is_sanitized(controls, resource):
    controls.raise_resource = resource
    with pytest.raises(civo.RunnerUnavailable) as error:
        civo.verified_runtime(controls)
    assert "private fake cluster diagnostic" not in str(error.value)


def test_matching_saved_hash_cannot_make_warning_only_binding_valid(controls):
    controls.binding["spec"]["validationActions"] = ["Warn"]
    controls.path.write_text(json.dumps(controls.receipt()))
    with pytest.raises(civo.RunnerUnavailable, match="not enforced"):
        civo.verified_runtime(controls)


def test_invalid_config_response_fails_closed(controls, monkeypatch):
    monkeypatch.setattr(controls, "run", lambda *args: "invalid-json")
    with pytest.raises(civo.RunnerUnavailable):
        civo.verified_runtime(controls)
