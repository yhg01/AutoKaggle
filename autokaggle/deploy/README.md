# AutoKaggle isolated code runner

This guide describes the existing BOLD installation. Verification receipts are generated locally and are excluded from this repository. A new checkout keeps code execution disabled until an operator configures and verifies the runner.


This preview uses the dedicated Civo cluster `ecc962fa-2f4c-4a3f-96c4-179af273fb7a` in `lon1`. It does not publish a website. The original Co-Scientist cluster was not changed.

`CivoRunner.status()` is the application gate. Code is available only when the runtime and controller acceptance records pass and current cluster controls still match. Missing evidence, a replaced or rebooted worker, a changed harness, or a failed current check disables execution. There is no environment flag that bypasses these checks. The saved JSON reports describe tests at their recorded times, not continuous health.

## Execution and data contract

The trusted application supplies one UTF-8 Python file, feature CSV bytes, an optional training CSV, and a frozen column schema. The program runs in gVisor with external networking disabled. Its image is the official Python image pinned in `runner/civo.py`; the observed Python version is 3.12.16. The image has the Python standard library and no scientific packages. The local scoring environment is a separate environment.

```python
from autokaggle.runner import CivoRunner

runner = CivoRunner()
status = runner.status()
if status["enabled"]:
    predictions = runner.submit(
        source_bytes,
        features=feature_csv_bytes,
        training=training_csv_bytes,
        expected_columns=["_autokaggle_id", "feature_a"],
        label_columns=["target"],
    )
    # Score these bytes inside the trusted application. Do not return them
    # or any worker file to a participant.
```

The fixed command runs `main.py --input /input/test_features.csv --output /output/predictions.csv`. Optional training data is at `/input/train.csv`. A prediction CSV has exactly `_autokaggle_id,prediction` and one row for every input ID. The controller verifies its structure and restores input order. The trusted scorer must also check the metric's value domain. Test labels are not an argument to the runner and have no worker volume. Training labels are permitted only in the training file selected by the trusted application.

| Bound | Value |
|---|---|
| Source | One Python file, 256 KiB maximum |
| Each input CSV | 50 MiB, 100,000 rows, 200 feature columns maximum |
| Worker | 1 CPU, 512 MiB memory, no GPU |
| Program | 100 seconds wall time, 90 seconds CPU time |
| Job | 120 seconds total, no automatic retry |
| Prediction file | 5,000,000 bytes maximum |
| Combined program output | 64 KiB maximum; discarded |
| Processes | 64 program processes; effective node pod limit 256 |
| Temporary memory filesystem | 128 MiB |
| Storage | Two separate 1 GiB Civo volumes per run |
| Concurrent execution | One controller run in the namespace |

A run has immutable source and harness ConfigMaps, a feature volume, and an output volume. The trusted staging pod attaches both volumes before the prediction Job starts. It copies only the approved feature and training files. The staging pod is deleted before the worker starts. Source, harness, and input mounts are read-only in the worker. Its root filesystem is read-only; it runs as user 65532 with no service token, host namespaces, host paths, added capabilities, secret references, or privilege escalation.

The worker exits before the trusted collector mounts its output volume. The collector rejects links, special files, oversized output, malformed rows, and invalid IDs. It reads only the prediction file. The application receives validated prediction bytes, not raw logs or other files. The controller removes all owned pods, Jobs, ConfigMaps, PVCs, and their backing volumes before it returns.

## Evidence and checks

- runtime-installation.json (local operational record; not included in this repository) records the pinned release and private backup path.
- runtime-activation.json (local operational record; not included in this repository) records the changed boot ID, Ready node, healthy system pods, and active process limit.
- runtime-verification.json (local operational record; not included in this repository) records actual gVisor identification, loopback-only interfaces, failed external/cluster/node connections, absent credentials and labels, read-only mounts, and bounded CPU, memory, process, file and time fixtures.
- controller-verification.json (local operational record; not included in this repository) records the complete synthetic staging and collection tests. Its `passed` and `cleanup_confirmed` fields must both be true. A partial or failed report does not enable execution.
- cluster-inspection.json (local operational record; not included in this repository) retains the earlier network-policy probe on the original worker. Its metadata records that older node; use the runtime report for the replacement worker's network isolation.
- RECOVERY-2026-10-27.md (local operational record; not included in this repository) records the initial installation error, worker replacement, and the exact credential-remediation limits.

The current gate checks the tested node's UID, boot ID, Ready condition and label; the sole selected worker; RuntimeClass mapping; restricted Pod Security; both deny policies; token-free service account; effective PID limit; Civo storage class; and exact admission policy and binding. The controller repeats this check before staging and before worker launch. It does not treat a RuntimeClass name as proof that a runtime works.

The runtime checks use fixed synthetic code. They establish the listed controls, not proof against every sandbox escape, side channel, or scientific data leak. The application must still prevent leakage through task design, feedback, repeated submissions, and exported artifacts. An offline worker can read its supplied features; network isolation cannot remove information already present in those features.

## Operator commands

Run commands from the repository root with the project Python environment active. The Civo CLI and kubectl must be installed. Civo credentials stay in the operator's private configuration. Each command obtains a mode-0600 temporary kubeconfig and deletes it. No command changes the operator's current Kubernetes context.

For a new, inspected worker, first update the fixed node/instance constants after checking their provider mapping. Installation refuses an unexpected base configuration or existing custom runtime files. It verifies the pinned official release checksum and creates private backups. Do not run it on an active worker without inspecting its workloads and storage.

```sh
python -m autokaggle.deploy.node_admin
python -m autokaggle.deploy.install_runtime
python -m autokaggle.deploy.activate_runtime --hard
python -m autokaggle.deploy.verify_runtime
python -m autokaggle.deploy.register_controls
python -m autokaggle.deploy.verify_controller
```

The install step only writes files. Its temporary administrative pod must be removed before activation. Activation uses the provider reboot operation, then verifies a new boot ID and healthy system pods. Never start k3s from a pod using `chroot`; this does not enter the host's other namespaces. The activation helper currently requires zero user PVCs and no non-system pods. Its initial setup checks must be reviewed before maintenance on a cluster with workloads.

The installed gVisor release is `20261019.0`. Containerd uses a separate handler named `autokaggle-runsc`, with `systrap` and `network=none`. The default runtime is preserved. The k3s version-3 base template and kubelet drop-in follow the upstream extension points. Managed node replacement can remove these custom files, so replacement closes the gate until installation and acceptance run again. [K3s runtime configuration](https://docs.k3s.io/advanced), [K3s kubelet configuration](https://docs.k3s.io/installation/configuration), [gVisor installation](https://gvisor.dev/docs/user_guide/install/), [gVisor containerd configuration](https://gvisor.dev/docs/user_guide/containerd/configuration/)

Network-none leaves internal loopback available. Kubernetes deny policy and Cilium explicit deny provide another control. Node PID limits and the harness resource limits add bounded resource use. These controls supplement the sandbox; they do not replace it. [gVisor networking](https://gvisor.dev/docs/user_guide/networking/), [Cilium deny policy](https://docs.cilium.io/en/stable/security/policy/deny/), [Kubernetes PID limits](https://kubernetes.io/docs/concepts/policy/pid-limiting/), [gVisor security model](https://gvisor.dev/docs/architecture_guide/security/)

## Failure recovery and operating limits

Civo volume creation and attachment are asynchronous and can take minutes. Trusted helpers allow a bounded 300-second readiness period and a 600-second lifetime. This does not extend the untrusted program's execution budget. The preview creates new volumes for each run, which adds latency.

If cleanup fails, the controller retains its namespace lock and refuses another run. If the controller process stops, the same lock remains. There is no automatic orphan reaper. An operator must inspect the exact owned run resources, stop any remaining worker, remove its temporary resources, confirm backing-volume deletion, and only then remove that run's lock. Never remove a lock while another controller is active. Never delete unrelated resources to clear a run.

To roll back the runtime, first disable scheduling to the verified node and stop code runs. Review the installation record and its private backups. Remove only the files added by that installation; restore only the corresponding original settings. Remove the temporary administrative pod, use a provider reboot, and verify all system pods. Re-run acceptance before enabling any subsequent runtime.

The current controller uses an operator kubeconfig on a trusted host. A public deployment needs a dedicated controller identity with restricted permissions and a maintained cleanup/recovery service. Uploaded code is never run by that trusted host. This prototype has no GPU, dependency installation, internet access, arbitrary images, or participant-controlled Pod specifications.
