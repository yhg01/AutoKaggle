"""Short-lived, fixed administrative probes for the designated AutoKaggle node.

Only trusted local scripts can use this module. It must never be exposed as a
participant API or imported into a worker image.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from .probe_cluster import Kubectl, private_kubeconfig

NODE = "k3s-autokaggle-bcaa-9bb8b8-node-pool-f405-1qjlx"
IMAGE = "docker.io/library/python@sha256:5789aa194f757888f41fa3d48e14b6feaa1b57c0af0b56fcb1372d6474d3bff0"


@contextmanager
def admin_pod(kube, *, writable=False, host_pid=False):
    namespace = "autokaggle-admin-" + uuid.uuid4().hex[:10]
    created = False
    try:
        kube.run("create", "-f", "-", document={"apiVersion": "v1", "kind": "Namespace", "metadata": {
            "name": namespace, "labels": {"pod-security.kubernetes.io/enforce": "privileged"}}})
        created = True
        kube.run("create", "-f", "-", document={"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "admin", "namespace": namespace}, "spec": {
            "nodeName": NODE, "automountServiceAccountToken": False, "enableServiceLinks": False,
            "hostPID": host_pid, "hostNetwork": False, "hostIPC": False,
            "restartPolicy": "Never", "activeDeadlineSeconds": 600,
            "containers": [{"name": "admin", "image": IMAGE, "command": ["python3", "-I", "-B", "-c", "import time; time.sleep(580)"],
                "securityContext": {"privileged": writable or host_pid, "readOnlyRootFilesystem": True},
                "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "1", "memory": "512Mi"}},
                "volumeMounts": [{"name": "host", "mountPath": "/host", "readOnly": not writable}, {"name": "scratch", "mountPath": "/tmp"}],
            }],
            "volumes": [{"name": "host", "hostPath": {"path": "/", "type": "Directory"}},
                        {"name": "scratch", "emptyDir": {"medium": "Memory", "sizeLimit": "256Mi"}}],
        }})
        kube.run("wait", "-n", namespace, "--for=condition=Ready", "pod/admin", "--timeout=90s", timeout=100)
        yield namespace
    finally:
        if created:
            kube.run("delete", "namespace", namespace, "--wait=true", "--timeout=60s", timeout=70)


INSPECTION = r'''
from pathlib import Path
import hashlib,json,tomllib
base=Path('/host')
folder=base/'var/lib/rancher/k3s/agent/etc/containerd'
report={'files':{},'services':[], 'kubelet_dropins':[]}
for name in ['config.toml','config.toml.tmpl','config-v3.toml.tmpl']:
    path=folder/name
    item={'exists':path.exists()}
    if path.exists():
        data=path.read_bytes(); item.update(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
        if name=='config.toml':
            config=tomllib.loads(data.decode()); item['version']=config.get('version')
            plugins=config.get('plugins',{}); runtime=plugins.get('io.containerd.cri.v1.runtime',{}).get('containerd',{})
            item['default_runtime']=runtime.get('default_runtime_name')
            item['runtimes']={key:{k:v for k,v in value.items() if k in ['runtime_type','runtime_path']} for key,value in runtime.get('runtimes',{}).items()}
        else:
            # Existing templates require exact review without printing potential registry credentials.
            item['has_custom_runtime']=b'runtimes.' in data
            item['uses_base_template']=b'template "base"' in data
    report['files'][name]=item
for name in ['runsc','containerd-shim-runsc-v1','gvisor-bin']:
    report['files'][name]={'exists':(base/'usr/local/bin'/name).exists()}
for path in (base/'etc/init.d').glob('*k3s*'):
    report['services'].append(path.name)
for path in (base/'var/lib/rancher/k3s/agent/etc/kubelet.conf.d').glob('*'):
    item={'name':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    for line in path.read_text().splitlines():
        if line.strip().startswith('podPidsLimit:'): item['podPidsLimit']=line.split(':',1)[1].strip()
    report['kubelet_dropins'].append(item)
report['config_dropins_exist']=(base/'etc/rancher/k3s/config.yaml.d').exists()
report['k3s_config_exists']=(base/'etc/rancher/k3s/config.yaml').exists()
print(json.dumps(report))
'''


def inspect_node():
    with private_kubeconfig() as path:
        kube = Kubectl(path)
        workloads = kube.json("get", "pods", "-A")["items"]
        report = {"checked_at": datetime.now(timezone.utc).isoformat(), "node": NODE,
            "workloads": [{"namespace": p["metadata"]["namespace"], "name": p["metadata"]["name"], "phase": p["status"].get("phase")} for p in workloads]}
        with admin_pod(kube) as namespace:
            report["node_config"] = json.loads(kube.run("exec", "-n", namespace, "admin", "--", "python3", "-I", "-B", "-c", INSPECTION))
        report["admin_cleanup_confirmed"] = True
    return report


if __name__ == "__main__":
    report = inspect_node()
    Path(__file__).with_name("node-inspection.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
