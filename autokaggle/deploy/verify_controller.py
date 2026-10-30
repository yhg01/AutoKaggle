"""Run fixed synthetic fixtures through the actual isolated Civo controller.

This command is an explicit operator test. It does not accept source files or
datasets. It publishes no endpoint and prints no worker data or logs.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from .probe_cluster import CLUSTER_ID, private_kubeconfig
from ..runner.civo import APPROVED_IMAGE, NAMESPACE, verified_runtime
from ..runner.controller import CivoController, ControllerFailure, KubectlTransport

FEATURES = b"_autokaggle_id,value,note\nr1,001,NA\nr2,002,\n"
TRAINING = b"value,note,target\n010,train,0\n011,train,1\n"
GOOD = b'''import argparse,csv,errno,socket
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args()
with open(a.input,newline='') as f: rows=list(csv.DictReader(f))
assert [(r['value'],r['note']) for r in rows]==[('001','NA'),('002','')]
assert sorted(p.name for p in Path('/input').iterdir() if p.is_file())==['test_features.csv','train.csv']
with open('/input/train.csv',newline='') as f: train=list(csv.DictReader(f))
assert [r['target'] for r in train]==['0','1']
assert not Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists()
assert not Path('/input/labels.csv').exists()
try:
    with open(a.input,'w') as f: f.write('bad')
    raise AssertionError('input writable')
except OSError as e: assert e.errno in [errno.EROFS,errno.EACCES,errno.EPERM]
try:
    c=socket.create_connection(('1.1.1.1',443),timeout=.5); c.close()
    raise AssertionError('external network connected')
except OSError: pass
with open(a.output,'w',newline='') as f:
    w=csv.writer(f);w.writerow(['_autokaggle_id','prediction'])
    for r in reversed(rows): w.writerow([r['_autokaggle_id'],'0'])
'''
SYMLINK = b"import os; os.symlink('/input/test_features.csv','/output/predictions.csv')\n"
LOG_OVERFLOW = b"import os; os.write(1,b'fixture-private-content'*10000)\n"


def cleanup_state(kube):
    counts = {}
    for kind in ("pods", "jobs", "persistentvolumeclaims", "configmaps"):
        counts[kind] = len(kube.json("get", kind, "-n", NAMESPACE, "-l", "app=autokaggle-runner")["items"])
    counts["persistentvolumes"] = len([v for v in kube.json("get", "persistentvolumes")["items"]
        if v.get("spec", {}).get("claimRef", {}).get("namespace") == NAMESPACE])
    return counts


def main():
    report = {"cluster_id": CLUSTER_ID, "image": APPROVED_IMAGE, "checked_at": datetime.now(timezone.utc).isoformat(),
              "fixed_synthetic_fixtures_only": True, "passed": False, "checks": []}
    target = Path(__file__).with_name("controller-verification.json")
    # Do not leave a previous successful receipt available during a new test.
    target.write_text(json.dumps(report, indent=2) + "\n")
    try:
        with private_kubeconfig() as config:
            kube = KubectlTransport(config)
            runtime = verified_runtime(kube)
            receipt = json.loads(Path(__file__).with_name("runtime-verification.json").read_text())
            report.update(node_uid=runtime["node_uid"], boot_id=receipt["boot_id"])
            if any(cleanup_state(kube).values()):
                raise RuntimeError("Existing run resources require review before integration testing.")
            runner = CivoController(kube)
            for name, source, should_pass in (("preserved_strings_and_training", GOOD, True),
                                               ("reject_symlink_output", SYMLINK, False),
                                               ("reject_log_overflow", LOG_OVERFLOW, False),
                                               ("next_run_after_failures", GOOD, True)):
                started = time.monotonic()
                print("Running fixed controller fixture: " + name, flush=True)
                succeeded = False
                failure = None
                try:
                    output = runner.submit(source, features=FEATURES, training=TRAINING,
                                           expected_columns=["_autokaggle_id", "value", "note"], label_columns=["target"])
                    succeeded = output == b"_autokaggle_id,prediction\nr1,0\nr2,0\n"
                    if not succeeded:
                        raise RuntimeError("The fixed prediction fixture returned unexpected output.")
                except ControllerFailure as error:
                    failure = type(error).__name__
                    if should_pass:
                        raise
                    if failure != "ControllerFailure":
                        raise RuntimeError("The negative fixture failed outside the expected worker boundary.") from None
                cleanup = cleanup_state(kube)
                passed = succeeded == should_pass and not any(cleanup.values())
                report["checks"].append({"name": name, "passed": passed, "seconds": round(time.monotonic()-started, 2),
                                         "result": "valid predictions" if succeeded else failure, "remaining_resources": cleanup})
                print(json.dumps(report["checks"][-1]), flush=True)
                if not passed:
                    raise RuntimeError("A fixed controller fixture or its cleanup failed.")
            report["cleanup_confirmed"] = not any(cleanup_state(kube).values())
            folder = Path(__file__).parent.parent / "runner"
            report["code_sha256"] = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                                     for name in ("controller.py", "entrypoint.py", "civo.py")}
            report["passed"] = all(x["passed"] for x in report["checks"]) and report["cleanup_confirmed"]
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
