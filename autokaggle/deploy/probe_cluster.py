"""Read the designated AutoKaggle cluster; optionally run fixed network probes.

No kube context is changed. The temporary kubeconfig is private and removed.
This program does not run uploaded code or install host software.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

CLUSTER_ID = "ecc962fa-2f4c-4a3f-96c4-179af273fb7a"
REGION = "lon1"
PROBE_IMAGE = "python:3.12-alpine"


@contextmanager
def private_kubeconfig():
    fd, path = tempfile.mkstemp(prefix="autokaggle-kube-", suffix=".yaml")
    os.chmod(path, 0o600)
    try:
        with os.fdopen(fd, "wb") as target:
            result = subprocess.run(
                ["civo", "kubernetes", "config", CLUSTER_ID, "--region", REGION],
                stdout=target, stderr=subprocess.PIPE, timeout=60,
            )
        if result.returncode or os.path.getsize(path) == 0:
            raise RuntimeError("Could not read the AutoKaggle kubeconfig.")
        yield path
    finally:
        Path(path).unlink(missing_ok=True)


class Kubectl:
    def __init__(self, kubeconfig):
        self.kubeconfig = kubeconfig

    def run(self, *args, document=None, timeout=45):
        result = subprocess.run(
            ["kubectl", "--kubeconfig", self.kubeconfig, "--request-timeout=25s", *args],
            input=json.dumps(document) if document is not None else None,
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode:
            # Commands never request secrets. Do not include command output in errors.
            raise RuntimeError(f"Cluster operation failed: {' '.join(args[:3])}")
        return result.stdout

    def json(self, *args):
        return json.loads(self.run(*args, "-o", "json"))


def inspect_cluster(kube):
    nodes = kube.json("get", "nodes")["items"]
    runtimes = kube.json("get", "runtimeclasses")["items"]
    pods = kube.json("get", "pods", "-n", "kube-system")["items"]
    policies = kube.json("get", "networkpolicies", "-A")["items"]
    report = {
        "cluster_id": CLUSTER_ID, "region": REGION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "inspection": "live read-only", "code_execution_enabled": False,
        "runtime_classes": [{"name": x["metadata"]["name"], "handler": x["handler"]} for x in runtimes],
        "nodes": [],
        "network_components": [
            {"pod": x["metadata"]["name"], "images": [c["image"] for c in x["spec"]["containers"]],
             "phase": x["status"].get("phase")}
            for x in pods if x["metadata"]["name"].startswith("cilium-")
        ],
        "network_policies": [{"namespace": x["metadata"]["namespace"], "name": x["metadata"]["name"]} for x in policies],
        "blockers": ["No approved sandbox execution path has passed the full acceptance suite."],
    }
    if not any(x["handler"] in {"runsc", "kata", "kata-qemu", "kata-clh"} for x in runtimes):
        report["blockers"].insert(0, "No gVisor or Kata runtime class is registered.")
    for node in nodes:
        name = node["metadata"]["name"]
        info = node["status"]["nodeInfo"]
        item = {"name": name, "os": info["osImage"], "kernel": info["kernelVersion"],
                "runtime": info["containerRuntimeVersion"], "kubelet": info["kubeletVersion"],
                "pod_pids_limit": None}
        try:
            config = json.loads(kube.run("get", "--raw", f"/api/v1/nodes/{name}/proxy/configz"))
            item["pod_pids_limit"] = config.get("kubeletconfig", {}).get("podPidsLimit")
        except (RuntimeError, ValueError):
            item["pid_check"] = "not accessible through kubelet configz"
        report["nodes"].append(item)
    try:
        config = kube.json("get", "configmap", "cilium-config", "-n", "kube-system")["data"]
        report["cilium_settings"] = {key: config.get(key) for key in (
            "enable-policy", "allow-localhost", "enable-host-firewall", "enable-remote-node-identity",
        )}
    except (RuntimeError, KeyError):
        report["cilium_settings"] = {"inspection": "unavailable"}
    if any(not isinstance(n["pod_pids_limit"], int) or not 1 <= n["pod_pids_limit"] <= 256 for n in report["nodes"]):
        report["blockers"].append("A finite per-pod PID limit of at most 256 is not verified on every runner node.")
    return report


def _pod(namespace, name, role):
    return {
        "apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": namespace, "labels": {"role": role}},
        "spec": {
            "automountServiceAccountToken": False, "enableServiceLinks": False,
            "hostNetwork": False, "hostPID": False, "hostIPC": False,
            "restartPolicy": "Never", "activeDeadlineSeconds": 300,
            "securityContext": {"runAsNonRoot": True, "runAsUser": 65532, "runAsGroup": 65532, "seccompProfile": {"type": "RuntimeDefault"}},
            "containers": [{"name": "probe", "image": PROBE_IMAGE,
                "command": ["python3", "-I", "-B", "-c", "from http.server import HTTPServer,BaseHTTPRequestHandler; HTTPServer(('0.0.0.0',8080),BaseHTTPRequestHandler).serve_forever()"],
                "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                "resources": {"requests": {"cpu": "50m", "memory": "48Mi"}, "limits": {"cpu": "200m", "memory": "96Mi"}},
            }],
        },
    }


def _tcp_probe(kube, namespace, source, targets):
    script = """import json,socket
targets = json.loads(__import__('sys').argv[1]); results = {}
for key, value in targets.items():
    try:
        connection = socket.create_connection(tuple(value), timeout=1.5)
        connection.close(); results[key] = True
    except OSError:
        results[key] = False
print(json.dumps(results))
"""
    return json.loads(kube.run("exec", "-n", namespace, source, "--", "python3", "-I", "-B", "-c", script, json.dumps(targets)))


def _dns_probe(kube, namespace, source):
    # Send a DNS question to the configured resolver. Do not print its response.
    script = """import json,socket,struct
resolver = next(line.split()[1] for line in open('/etc/resolv.conf') if line.startswith('nameserver '))
question = b''.join(bytes([len(part)]) + part.encode() for part in 'kubernetes.default.svc.cluster.local'.split('.')) + b'\\0'
packet = struct.pack('!HHHHHH',1234,256,1,0,0,0) + question + struct.pack('!HH',1,1)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(1.5)
try:
    s.sendto(packet,(resolver,53)); data=s.recv(4096); ok=len(data)>=12 and data[:2]==packet[:2]
except OSError:
    ok=False
finally:
    s.close()
print(json.dumps(ok))
"""
    return json.loads(kube.run("exec", "-n", namespace, source, "--", "python3", "-I", "-B", "-c", script))


def network_probe(kube):
    namespace = "autokaggle-probe-" + uuid.uuid4().hex[:10]
    report = {"namespace": namespace, "image": PROBE_IMAGE, "trusted_fixed_code_only": True, "cleanup_confirmed": False}
    created = False
    try:
        kube.run("create", "-f", "-", document={"apiVersion": "v1", "kind": "Namespace", "metadata": {
            "name": namespace, "labels": {"pod-security.kubernetes.io/enforce": "restricted", "pod-security.kubernetes.io/enforce-version": "v1.35"},
        }})
        created = True
        for name, role in (("client", "isolated"), ("peer", "control")):
            kube.run("create", "-f", "-", document=_pod(namespace, name, role))
        kube.run("wait", "-n", namespace, "--for=condition=Ready", "pod", "--all", "--timeout=120s", timeout=130)
        client = kube.json("get", "pod", "client", "-n", namespace)
        peer = kube.json("get", "pod", "peer", "-n", namespace)
        service = kube.json("get", "service", "kubernetes", "-n", "default")
        node = kube.json("get", "node", client["spec"]["nodeName"])
        node_ip = next(x["address"] for x in node["status"]["addresses"] if x["type"] == "InternalIP")
        targets = {"peer": [peer["status"]["podIP"], 8080], "api": [service["spec"]["clusterIP"], 443],
                   "public_ip": ["1.1.1.1", 443], "node_kubelet": [node_ip, 10250], "metadata": ["169.254.169.254", 80]}
        report["image_ids"] = [s.get("imageID") for p in (client, peer) for s in p["status"].get("containerStatuses", [])]
        report["baseline"] = _tcp_probe(kube, namespace, "client", targets)
        report["baseline"]["dns"] = _dns_probe(kube, namespace, "client")
        report["baseline"]["ingress"] = _tcp_probe(kube, namespace, "peer", {"client": [client["status"]["podIP"], 8080]})["client"]
        selector = {"matchLabels": {"role": "isolated"}}
        kube.run("create", "-f", "-", document={"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": {"name": "deny-all", "namespace": namespace}, "spec": {"podSelector": selector, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": []}})
        kube.run("create", "-f", "-", document={"apiVersion": "cilium.io/v2", "kind": "CiliumNetworkPolicy",
            "metadata": {"name": "explicit-deny-all", "namespace": namespace}, "spec": {"endpointSelector": selector,
                "ingressDeny": [{"fromEntities": ["all"]}], "egressDeny": [{"toEntities": ["all"]}]}})
        # Bound propagation time. All probes use new connections.
        time.sleep(3)
        report["after_policy"] = _tcp_probe(kube, namespace, "client", targets)
        report["after_policy"]["dns"] = _dns_probe(kube, namespace, "client")
        report["after_policy"]["ingress"] = _tcp_probe(kube, namespace, "peer", {"client": [client["status"]["podIP"], 8080]})["client"]
        report["control_after_policy"] = _tcp_probe(kube, namespace, "peer", {"api": targets["api"], "public_ip": targets["public_ip"]})
        report["verified_denials"] = [key for key in report["baseline"] if report["baseline"][key] and not report["after_policy"][key]]
        report["inconclusive_targets"] = [key for key in report["baseline"] if not report["baseline"][key]]
        report["passed"] = all(key in report["verified_denials"] for key in ("peer", "api", "public_ip", "dns", "ingress", "node_kubelet")) and all(report["control_after_policy"].values()) and not any(report["after_policy"].values())
        report["scope"] = "Observed TCP, DNS and pod-ingress paths only; not proof of complete network or runtime isolation."
    finally:
        if created:
            kube.run("delete", "namespace", namespace, "--wait=true", "--timeout=60s", timeout=70)
            report["cleanup_confirmed"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", action="store_true", help="Create and delete a temporary namespace with trusted network probes.")
    parser.add_argument("--output", type=Path, help="Save the sanitized JSON report.")
    args = parser.parse_args()
    with private_kubeconfig() as config:
        kube = Kubectl(config)
        report = inspect_cluster(kube)
        if args.network:
            report["network_probe"] = network_probe(kube)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered)


if __name__ == "__main__":
    main()
