"""Install and verify private review TLS on the fixed AutoKaggle cluster.

Run from the repository root with the project Python environment. No current
Kubernetes context is changed. The script never prints private credentials.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from autokaggle.deploy.probe_cluster import CLUSTER_ID, REGION, Kubectl, private_kubeconfig

HERE = Path(__file__).resolve().parent
VERSION = "v1.21.3"
MANIFEST_URL = f"https://github.com/cert-manager/cert-manager/releases/download/{VERSION}/cert-manager.yaml"
MANIFEST_SHA256 = "c04a51295adda2b1a775146751f973e787190778c7f35180861d9678876e5c74"
NAMESPACE = "autokaggle-web"
HOST = f"{CLUSTER_ID}.k8s.civo.com"
CERTIFICATE = "autokaggle-web-tls"


def apply_bytes(kube, data):
    result = subprocess.run(
        ["kubectl", "--kubeconfig", kube.kubeconfig, "--request-timeout=45s",
         "apply", "--server-side", "--field-manager=autokaggle-web-tls", "-f", "-"],
        input=data, capture_output=True, timeout=60,
    )
    if result.returncode:
        # Inputs contain only the official release and this public TLS manifest.
        # Do not print arbitrary cluster responses or secret objects.
        raise RuntimeError("TLS resource application failed; inspect the named resource status.")


def wait_ready(kube, kind, name, namespace, *, timeout=300):
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        try:
            item = kube.json("get", kind, name, "-n", namespace)
            status = item.get("status", {})
            if kind == "deployment":
                ready = (status.get("observedGeneration", 0) >= item["metadata"].get("generation", 1)
                         and status.get("availableReplicas", 0) >= item["spec"].get("replicas", 1))
                summary = {"available": status.get("availableReplicas", 0)}
            else:
                conditions = status.get("conditions", [])
                ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
                summary = {c.get("type"): c.get("reason") for c in conditions}
            if ready:
                print(f"{kind}/{name}: Ready", flush=True)
                return item
            if summary != previous:
                print(json.dumps({"waiting_for": f"{kind}/{name}", "status": summary}), flush=True)
                previous = summary
        except RuntimeError:
            pass
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for {kind}/{name}.")


def install(kube, ca_file):
    existing = kube.json("get", "deployments", "-n", "cert-manager")["items"]
    if existing:
        images = [c["image"] for d in existing for c in d["spec"]["template"]["spec"]["containers"]]
        if any(not image.endswith(":" + VERSION) for image in images):
            raise RuntimeError("An existing cert-manager installation has a different version; inspect it before changing it.")
        print("The pinned cert-manager release is already installed.", flush=True)
    else:
        with urllib.request.urlopen(MANIFEST_URL, context=ssl.create_default_context(cafile=ca_file), timeout=45) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != MANIFEST_SHA256:
            raise RuntimeError("The official cert-manager manifest checksum changed.")
        apply_bytes(kube, data)
        print(f"Applied official cert-manager {VERSION}.", flush=True)
    for name in ("cert-manager", "cert-manager-cainjector", "cert-manager-webhook"):
        wait_ready(kube, "deployment", name, "cert-manager")


def request(kube):
    # The namespace is first because the Issuer and Certificate require it.
    docs = (HERE / "web-tls.yaml").read_bytes().split(b"\n---\n")
    apply_bytes(kube, docs[0])
    # A new webhook can be available before its CA injection has completed.
    for attempt in range(6):
        try:
            apply_bytes(kube, b"\n---\n".join(docs[1:]))
            break
        except RuntimeError:
            if attempt == 5:
                raise
            print("Waiting for the cert-manager admission service.", flush=True)
            time.sleep(10)
    wait_ready(kube, "issuer", "autokaggle-letsencrypt", NAMESPACE)
    return wait_ready(kube, "certificate", CERTIFICATE, NAMESPACE, timeout=600)


def verify(kube, ca_file):
    certificate = wait_ready(kube, "certificate", CERTIFICATE, NAMESPACE, timeout=60)
    encoded = kube.run("get", "secret", CERTIFICATE, "-n", NAMESPACE,
                       "-o", "jsonpath={.data.tls\\.crt}")
    chain = base64.b64decode(encoded, validate=True)
    marker = b"-----END CERTIFICATE-----"
    first = chain.find(marker) + len(marker)
    if first < len(marker):
        raise RuntimeError("The TLS Secret does not contain a PEM certificate.")
    leaf, intermediates = chain[:first] + b"\n", chain[first:]
    with tempfile.TemporaryDirectory(prefix="autokaggle-public-cert-") as directory:
        leaf_path = Path(directory) / "leaf.pem"
        chain_path = Path(directory) / "intermediates.pem"
        leaf_path.write_bytes(leaf)
        chain_path.write_bytes(intermediates)
        result = subprocess.run(
            ["openssl", "verify", "-CAfile", ca_file, "-untrusted", str(chain_path),
             "-verify_hostname", HOST, str(leaf_path)], capture_output=True, timeout=15,
        )
        if result.returncode:
            raise RuntimeError("The issued certificate did not pass trusted chain and hostname verification.")
        decoded = ssl._ssl._test_decode_cert(str(leaf_path))
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "cluster_id": CLUSTER_ID, "region": REGION, "namespace": NAMESPACE, "hostname": HOST,
        "cert_manager_version": VERSION, "official_manifest_url": MANIFEST_URL,
        "official_manifest_sha256": MANIFEST_SHA256,
        "issuer": "autokaggle-letsencrypt", "certificate": CERTIFICATE,
        "certificate_ready": True, "trusted_chain_and_hostname_verified": True,
        "certificate_sha256": hashlib.sha256(ssl.PEM_cert_to_DER_cert(leaf.decode())).hexdigest(),
        "not_before": decoded.get("notBefore"), "not_after": decoded.get("notAfter"),
        "issuer_name": decoded.get("issuer"), "renewal_time": certificate.get("status", {}).get("renewalTime"),
        "verification_scope": "Issued public certificate chain. The app route is managed separately.",
    }
    (HERE / "web-tls.verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "request", "verify", "all"), default="all", nargs="?")
    args = parser.parse_args()
    import certifi
    with private_kubeconfig() as path:
        kube = Kubectl(path)
        if args.action in {"install", "all"}:
            install(kube, certifi.where())
        if args.action in {"request", "all"}:
            request(kube)
        if args.action in {"verify", "all"}:
            verify(kube, certifi.where())


if __name__ == "__main__":
    main()
