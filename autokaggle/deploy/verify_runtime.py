"""Bounded, trusted acceptance fixtures for the installed AutoKaggle runtime."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from .node_admin import NODE, IMAGE
from .probe_cluster import CLUSTER_ID, Kubectl, private_kubeconfig

CHECKS = r'''
import ctypes,errno,json,os,resource,socket,subprocess,sys,time
from pathlib import Path
report={'uid':os.getuid(),'uname':os.uname().release,'interfaces':socket.if_nameindex(),'python':sys.version.split()[0]}
result=subprocess.run(['dmesg'],capture_output=True,text=True)
report['gvisor_dmesg']='gVisor' in result.stdout
report['token_absent']=not Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists()
report['host_config_absent']=not Path('/etc/rancher/k3s/config.yaml').exists()
report['labels_absent']=not Path('/input/labels.csv').exists()
report['input_files']=sorted(p.name for p in Path('/input').iterdir() if not p.name.startswith('.'))
for key,path in [('root_read_only','/write-test'),('input_read_only','/input/test_features.csv')]:
    try:
        with open(path,'w') as f: f.write('unexpected')
        report[key]=False
    except OSError as e:
        report[key]=e.errno in [errno.EROFS,errno.EACCES,errno.EPERM]
targets=json.loads(__import__('sys').argv[1])
report['network_denied']={}
for name,target in targets.items():
    try:
        connection=socket.create_connection(tuple(target),timeout=.7); connection.close(); report['network_denied'][name]=False
    except OSError:
        report['network_denied'][name]=True
server=socket.socket();server.bind(('127.0.0.1',0));server.listen()
client=socket.create_connection(server.getsockname()); accepted,_=server.accept()
report['loopback_works']=True;accepted.close();client.close();server.close()
try:
    s=socket.socket(socket.AF_INET6,socket.SOCK_STREAM);s.settimeout(.7);s.connect(('2606:4700:4700::1111',443));report['ipv6_external_denied']=False
except OSError:
    report['ipv6_external_denied']=True
finally:
    s.close()
resource.setrlimit(resource.RLIMIT_NPROC,(32,32));children=[];limited=False
try:
    for _ in range(40):
        try: pid=os.fork()
        except OSError as e:
            limited=e.errno==errno.EAGAIN;break
        if pid==0: time.sleep(10);os._exit(0)
        children.append(pid)
finally:
    for pid in children:
        try:os.kill(pid,9)
        except ProcessLookupError:pass
    for pid in children:os.waitpid(pid,0)
report['process_limit_enforced']=limited;report['children_before_limit']=len(children)
resource.setrlimit(resource.RLIMIT_FSIZE,(1048576,1048576))
try:
    with open('/scratch/bound-test','wb') as f:f.write(b'x'*1048577)
    report['file_limit_enforced']=False
except OSError as e:
    report['file_limit_enforced']=e.errno==errno.EFBIG
start=time.monotonic();cpu=time.process_time()
while time.monotonic()-start<2:pass
report['cpu_seconds_in_two_wall_seconds']=round(time.process_time()-cpu,3)
report['cpu_quota_observed']=report['cpu_seconds_in_two_wall_seconds']<1.5
print(json.dumps(report))
'''


def pod_spec(namespace, name, runtime, command, *, memory="256Mi"):
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"namespace": namespace, "name": name}, "spec": {
        "nodeName": NODE, "runtimeClassName": runtime, "automountServiceAccountToken": False, "enableServiceLinks": False,
        "restartPolicy": "Never", "activeDeadlineSeconds": 90, "terminationGracePeriodSeconds": 2,
        "securityContext": {"runAsNonRoot": True, "runAsUser": 65532, "runAsGroup": 65532, "fsGroup": 65532, "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [{"name": "fixture", "image": IMAGE, "command": command,
            "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
            "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "250m", "memory": memory}},
            "volumeMounts": [{"name": "input", "mountPath": "/input", "readOnly": True}, {"name": "scratch", "mountPath": "/scratch"}],
        }],
        "volumes": [{"name": "input", "configMap": {"name": "features", "defaultMode": 292}},
                    {"name": "scratch", "emptyDir": {"medium": "Memory", "sizeLimit": "8Mi"}}],
    }}


def wait_finished(kube, namespace, name, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pod = kube.json("get", "pod", name, "-n", namespace)
        if pod["status"].get("phase") in {"Succeeded", "Failed"}:
            return pod
        time.sleep(2)
    raise RuntimeError("Trusted runtime fixture did not finish within its test bound.")


def main():
    namespace = "autokaggle-runtime-test-" + uuid.uuid4().hex[:8]
    runtime = "autokaggle-test-" + uuid.uuid4().hex[:8]
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "cluster_id": CLUSTER_ID, "node": NODE, "release": "20261019.0", "image": IMAGE, "trusted_fixtures_only": True}
    created = False
    with private_kubeconfig() as path:
        kube = Kubectl(path)
        try:
            kube.run("create", "-f", "-", document={"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace, "labels": {"pod-security.kubernetes.io/enforce": "restricted"}}})
            created = True
            kube.run("create", "-f", "-", document={"apiVersion": "node.k8s.io/v1", "kind": "RuntimeClass", "metadata": {"name": runtime}, "handler": "autokaggle-runsc"})
            kube.run("create", "-f", "-", document={"apiVersion": "v1", "kind": "ConfigMap", "immutable": True,
                "metadata": {"name": "features", "namespace": namespace}, "data": {"test_features.csv": "id,value\n001,4\n002,8\n"}})
            api = kube.json("get", "service", "kubernetes", "-n", "default")["spec"]["clusterIP"]
            dns = kube.json("get", "service", "kube-dns", "-n", "kube-system")["spec"]["clusterIP"]
            node = kube.json("get", "node", NODE)
            report["node_uid"] = node["metadata"]["uid"]
            report["boot_id"] = node["status"]["nodeInfo"]["bootID"]
            node_ip = next(x["address"] for x in node["status"]["addresses"] if x["type"] == "InternalIP")
            targets = {"api": [api,443], "dns_tcp": [dns,53], "public": ["1.1.1.1",443], "node_kubelet": [node_ip,10250], "metadata": ["169.254.169.254",80]}
            kube.run("create", "-f", "-", document=pod_spec(namespace,"access",runtime,["python3","-I","-B","-c",CHECKS,json.dumps(targets)]))
            access = wait_finished(kube,namespace,"access")
            report["access_phase"] = access["status"]["phase"]
            if report["access_phase"] != "Succeeded":
                report["access_container_status"] = access["status"].get("containerStatuses")
                raise RuntimeError("Trusted access fixture failed; inspect its bounded, non-sensitive diagnostics.")
            report["access"] = json.loads(kube.run("logs","-n",namespace,"access","--limit-bytes=20000"))
            # This bounded allocation must be killed by the pod's memory cap.
            memory = "import time; blocks=[]\nfor _ in range(80):\n blocks.append(bytearray(8*1024*1024)); time.sleep(.01)\ntime.sleep(10)"
            kube.run("create", "-f", "-", document=pod_spec(namespace,"memory",runtime,["python3","-I","-B","-c",memory]))
            mem = wait_finished(kube,namespace,"memory")
            state = mem["status"].get("containerStatuses",[{}])[0].get("state",{}).get("terminated",{})
            report["memory_limit"] = {"phase":mem["status"]["phase"],"reason":state.get("reason"),"exit_code":state.get("exitCode")}
            deadline_pod = pod_spec(namespace,"deadline",runtime,["python3","-I","-B","-c","import time; time.sleep(60)"])
            deadline_pod["spec"]["activeDeadlineSeconds"] = 8
            kube.run("create", "-f", "-", document=deadline_pod)
            timed = wait_finished(kube,namespace,"deadline",timeout=40)
            report["time_limit"] = {"phase":timed["status"]["phase"],"reason":timed["status"].get("reason")}
            config = json.loads(kube.run("get","--raw",f"/api/v1/nodes/{NODE}/proxy/configz"))
            report["pod_pids_limit"] = config["kubeletconfig"].get("podPidsLimit")
            checks = report["access"]
            keys = ["gvisor_dmesg","token_absent","host_config_absent","labels_absent","root_read_only","input_read_only","loopback_works","ipv6_external_denied","process_limit_enforced","file_limit_enforced","cpu_quota_observed"]
            report["passed"] = (all(checks[key] for key in keys) and checks["uid"]==65532 and all(checks["network_denied"].values())
                and checks["input_files"]==["test_features.csv"] and report["memory_limit"]["reason"]=="OOMKilled"
                and report["time_limit"]["reason"]=="DeadlineExceeded" and report["pod_pids_limit"]==256)
        finally:
            if created:
                kube.run("delete","namespace",namespace,"--wait=true","--timeout=60s",timeout=70)
                kube.run("delete","runtimeclass",runtime,"--ignore-not-found=true")
                report["cleanup_confirmed"] = True
            Path(__file__).with_name("runtime-verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
    if not report.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
