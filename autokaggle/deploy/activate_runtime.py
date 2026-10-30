"""Activate the installed runtime by rebooting the dedicated Civo worker.

No service is started from a container. Only the fixed, verified worker is
eligible. The Civo key is read in memory and is never included in output.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import ssl
import subprocess
import time
import urllib.request

import certifi

from .node_admin import NODE
from .probe_cluster import CLUSTER_ID, REGION, Kubectl, private_kubeconfig

INSTANCE = "32326a5b-e884-47aa-9f46-6cf99be4637a"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hard", action="store_true", help="Use the provider hard reboot after an ineffective soft reboot.")
    args = parser.parse_args()
    report = {"cluster_id": CLUSTER_ID, "node": NODE, "instance": INSTANCE,
              "started_at": datetime.now(timezone.utc).isoformat(), "reboot": "hard" if args.hard else "soft"}
    result = subprocess.run(["civo", "kubernetes", "show", CLUSTER_ID, "--region", REGION, "-o", "json"],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("Cannot verify the dedicated cluster mapping.")
    cluster = json.loads(result.stdout)
    # Inspect the nested mapping in memory; never print Civo's instance records.
    instances = [instance for pool in cluster.get("pools", []) for instance in pool.get("instances", [])]
    matching = [item for item in instances if item.get("id") == INSTANCE]
    if len(matching) != 1 or matching[0].get("hostname") != NODE or matching[0].get("status") != "ACTIVE":
        raise RuntimeError("The provider worker mapping changed; activation stopped.")
    install = json.loads(Path(__file__).with_name("runtime-installation.json").read_text())
    if install.get("node") != NODE or install.get("admin_cleanup_confirmed") is not True:
        raise RuntimeError("A completed installation with administrator cleanup is required.")
    with private_kubeconfig() as path:
        kube = Kubectl(path)
        node = kube.json("get", "node", NODE)
        report["node_uid"] = node["metadata"]["uid"]
        report["previous_boot_id"] = node["status"]["nodeInfo"]["bootID"]
        if kube.json("get", "persistentvolumeclaims", "-A")["items"]:
            raise RuntimeError("Unexpected persistent workloads require review before reboot.")
        pods = kube.json("get", "pods", "-A")["items"]
        if any(p["metadata"]["namespace"] != "kube-system" for p in pods):
            raise RuntimeError("Unexpected non-system pods require review before reboot.")
        config = json.loads((Path.home() / ".civo.json").read_text())
        key = config["apikeys"][config["meta"]["current_apikey"]]
        Path(__file__).with_name("runtime-activation.json").write_text(json.dumps(report, indent=2) + "\n")
        action = "reboots" if args.hard else "soft_reboots"
        request = urllib.request.Request(
            f"https://api.civo.com/v2/instances/{INSTANCE}/{action}?region={REGION}",
            method="POST", data=b"", headers={"Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context(cafile=certifi.where())) as response:
                answer = json.load(response)
                if response.status != 200 or answer.get("result") != "success":
                    raise RuntimeError("The provider did not confirm the worker reboot.")
        except Exception:
            raise RuntimeError("The provider reboot request did not return a confirmed result.") from None
        del key, config, request
        print("Provider reboot accepted for the verified AutoKaggle worker.", flush=True)
        deadline = time.monotonic() + 600
        last_notice = 0
        while time.monotonic() < deadline:
            try:
                node = kube.json("get", "node", NODE)
                ready = any(c["type"] == "Ready" and c["status"] == "True" for c in node["status"].get("conditions", []))
                boot = node["status"]["nodeInfo"]["bootID"]
                if ready and boot != report["previous_boot_id"]:
                    configz = json.loads(kube.run("get", "--raw", f"/api/v1/nodes/{NODE}/proxy/configz"))
                    pods = kube.json("get", "pods", "-n", "kube-system")["items"]
                    healthy = all(p["status"].get("phase") == "Succeeded" or (
                        p["status"].get("phase") == "Running" and
                        all(c.get("ready") for c in p["status"].get("containerStatuses", [])) and
                        len(p["status"].get("containerStatuses", [])) == len(p["spec"]["containers"])) for p in pods)
                    if healthy and configz.get("kubeletconfig", {}).get("podPidsLimit") == 256:
                        report.update(boot_id=boot, node_ready=True, system_pods_healthy=True, pod_pids_limit=256,
                                      finished_at=datetime.now(timezone.utc).isoformat())
                        Path(__file__).with_name("runtime-activation.json").write_text(json.dumps(report, indent=2) + "\n")
                        print(json.dumps(report, indent=2))
                        return
            except (RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired):
                pass
            if time.monotonic() - last_notice >= 40:
                print("Waiting for the same worker to reboot and its system pods to become Ready.", flush=True)
                last_notice = time.monotonic()
            time.sleep(5)
        raise RuntimeError("Worker activation did not pass health checks within ten minutes.")


if __name__ == "__main__":
    main()
