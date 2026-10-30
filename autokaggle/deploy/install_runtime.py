"""Install the pinned sandbox handler through a temporary node admin pod.

This fixed operator program targets only the new AutoKaggle node. It backs up
existing configuration and adds files without replacing settings.
It does not enable participant code submissions.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .node_admin import admin_pod, NODE
from .probe_cluster import Kubectl, private_kubeconfig

RELEASE = "20261019.0"
ARCHIVE_SHA512 = "7cbc2aeeee809dcccfb40e612504a1b76f2c119790cee59e482f7b35428cccc4f71705e7e322442d07d1f7d29b5d9e72e31319fc3088d6dcbec9fc7c1f0d8881"
EXPECTED_CONFIG_SHA256 = "f9b9cd5e537dfa7012535f58264877470d3e9864402212120c77050600ac3b10"

INSTALL = r'''
from pathlib import Path
import hashlib,json,os,shutil,subprocess,tarfile,time,urllib.request
base=Path('/host'); release='20261019.0'
expected='7cbc2aeeee809dcccfb40e612504a1b76f2c119790cee59e482f7b35428cccc4f71705e7e322442d07d1f7d29b5d9e72e31319fc3088d6dcbec9fc7c1f0d8881'
config=base/'var/lib/rancher/k3s/agent/etc/containerd/config.toml'
assert hashlib.sha256(config.read_bytes()).hexdigest()=='f9b9cd5e537dfa7012535f58264877470d3e9864402212120c77050600ac3b10','Containerd configuration changed; inspect before retry.'
paths=['usr/local/bin/runsc','usr/local/bin/containerd-shim-runsc-v1','usr/local/bin/gvisor-bin',
 'var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.tmpl','etc/containerd/autokaggle-runsc.toml',
 'var/lib/rancher/k3s/agent/etc/kubelet.conf.d/90-autokaggle-pids.conf']
for name in paths:
    assert not (base/name).exists() and not (base/name).is_symlink(), 'Existing target requires review: '+name
assert not config.with_name('config.toml.tmpl').exists(), 'Legacy template requires review.'
archive=Path('/tmp/gvisor.tar.bz2')
url='https://github.com/google/gvisor/releases/download/release-'+release+'/gvisor-x86_64.tar.bz2'
with urllib.request.urlopen(url,timeout=60) as response, archive.open('xb') as out:
    total=0
    while chunk:=response.read(1024*1024):
        total+=len(chunk); assert total<100*1024*1024, 'Archive exceeds reviewed bound'; out.write(chunk)
assert hashlib.sha512(archive.read_bytes()).hexdigest()==expected,'Official release hash mismatch'
unpack=Path('/tmp/unpack'); unpack.mkdir()
with tarfile.open(archive) as tar:
    total=0
    for member in tar.getmembers():
        p=Path(member.name)
        assert not p.is_absolute() and '..' not in p.parts
        assert p.parts[0] in {'runsc','containerd-shim-runsc-v1','gvisor-bin'}
        assert member.isfile() or member.isdir(), 'Archive links/devices rejected'
        total+=member.size; assert total<200*1024*1024
    tar.extractall(unpack,filter='data')
version=subprocess.run([str(unpack/'runsc'),'--version'],capture_output=True,text=True,check=True).stdout.strip()
backup=base/('var/lib/autokaggle-admin/backups/runtime-'+release+'-'+str(int(time.time())))
backup.mkdir(parents=True,mode=0o700)
for source in [config,base/'var/lib/rancher/k3s/agent/etc/kubelet.conf.d/00-k3s-defaults.conf',base/'etc/rancher/k3s/config.yaml']:
    if source.exists():
        destination=backup/source.name; shutil.copyfile(source,destination); destination.chmod(0o600)
manifest={'release':release,'archive_sha512':expected,'new_paths':paths,'previous_containerd_sha256':hashlib.sha256(config.read_bytes()).hexdigest()}
(backup/'manifest.json').write_text(json.dumps(manifest,indent=2)); (backup/'manifest.json').chmod(0o600)
for name in ['runsc','containerd-shim-runsc-v1']:
    target=base/'usr/local/bin'/name
    with target.open('xb') as f: f.write((unpack/name).read_bytes())
    target.chmod(0o755)
shutil.copytree(unpack/'gvisor-bin',base/'usr/local/bin/gvisor-bin')
for path in (base/'usr/local/bin/gvisor-bin').rglob('*'):
    path.chmod(0o755 if path.is_dir() or os.access(path,os.X_OK) else 0o644)
(base/'usr/local/bin/gvisor-bin').chmod(0o755)
contents={
paths[3]:''' + repr('''{{ template "base" . }}

[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.'autokaggle-runsc']
  runtime_type = "io.containerd.runsc.v1"
  runtime_path = "/usr/local/bin/containerd-shim-runsc-v1"
[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.'autokaggle-runsc'.options]
  TypeUrl = "io.containerd.runsc.v1.options"
  ConfigPath = "/etc/containerd/autokaggle-runsc.toml"
''') + r''',
paths[4]:'[runsc_config]\n  platform = "systrap"\n  network = "none"\n',
paths[5]:'apiVersion: kubelet.config.k8s.io/v1beta1\nkind: KubeletConfiguration\npodPidsLimit: 256\n'}
for name,content in contents.items():
    path=base/name; path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f: f.write(content)
    path.chmod(0o644)
print(json.dumps({'version':version,'backup_path':'/'+str(backup.relative_to(base)), 'release':release,'archive_sha512':expected,'installed_paths':paths}))
'''


def main():
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "node": NODE, "code_execution_enabled": False}
    with private_kubeconfig() as path:
        kube = Kubectl(path)
        with admin_pod(kube, writable=True) as namespace:
            report["installation"] = json.loads(kube.run("exec", "-n", namespace, "admin", "--", "python3", "-I", "-B", "-c", INSTALL, timeout=180))
        report["admin_cleanup_confirmed"] = True
        # Never start a host service from a pod. Its namespaces and cgroup can be
        # inherited even after chroot. Activate through the provider control
        # plane only after this administrative pod has been removed.
        report["activation"] = "pending provider reboot; no host service was started from a pod"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    Path(__file__).with_name("runtime-installation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
