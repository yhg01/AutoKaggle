"""Apply fixed namespace controls only after this node passes runtime tests."""
import hashlib
import json
from pathlib import Path
import time

from .probe_cluster import Kubectl, private_kubeconfig
from ..runner.civo import NAMESPACE, _runtime_receipt, verified_runtime


def main():
    receipt = _runtime_receipt()
    if receipt is None:
        raise RuntimeError("A passing runtime acceptance record is required.")
    with private_kubeconfig() as path:
        kube = Kubectl(path)
        node = kube.json("get", "node", receipt["node"])
        if (node["metadata"]["uid"] != receipt["node_uid"] or
                node["status"]["nodeInfo"]["bootID"] != receipt["boot_id"]):
            raise RuntimeError("The tested worker changed; repeat runtime acceptance.")
        kube.run("apply", "--server-side", "-f", "-", document={"apiVersion": "v1", "kind": "Namespace", "metadata": {
            "name": NAMESPACE, "labels": {"pod-security.kubernetes.io/enforce": "restricted",
                                           "pod-security.kubernetes.io/enforce-version": "v1.35"}}})
        for name in ("runner-namespace.yaml", "runner-admission.yaml"):
            manifest = str(Path(__file__).with_name(name))
            kube.run("apply", "--server-side", "--dry-run=server", "-f", manifest)
            kube.run("apply", "--server-side", "-f", manifest)
        deadline = time.monotonic() + 20
        while True:
            policy = kube.json("get", "validatingadmissionpolicy", "autokaggle-fixed-runner")
            if policy.get("status", {}).get("observedGeneration") == policy["metadata"]["generation"]:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Admission type checking has not completed.")
            time.sleep(1)
        if policy.get("status", {}).get("typeChecking", {}).get("expressionWarnings"):
            raise RuntimeError("Admission expressions did not pass type checking.")
        for resource, key in (("validatingadmissionpolicy", "admission_sha256"),
                              ("validatingadmissionpolicybinding", "admission_binding_sha256")):
            current = kube.json("get", resource, "autokaggle-fixed-runner")
            receipt[key] = hashlib.sha256(json.dumps(current["spec"], sort_keys=True).encode()).hexdigest()
        kube.run("label", "node", receipt["node"], "autokaggle.openphil.org/sandbox=gvisor-verified", "--overwrite")
        Path(__file__).with_name("runtime-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(verified_runtime(kube), indent=2))


if __name__ == "__main__":
    main()
