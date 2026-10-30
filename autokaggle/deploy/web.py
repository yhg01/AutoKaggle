"""Deploy the private review service to the fixed AutoKaggle Civo cluster.

Source and dependency versions are immutable per release. No local data, model
keys, mail files, or test results enter the source bundle. Secrets go to kubectl
on stdin. This command never changes the operator's current kube context.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import tarfile

from dotenv import dotenv_values

from .probe_cluster import CLUSTER_ID, Kubectl, private_kubeconfig

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "autokaggle"
NAMESPACE = "autokaggle-web"
HOST = CLUSTER_ID + ".k8s.civo.com"
PRIVATE_ENV = Path.home() / ".config/autokaggle/web.env"
MAIL_SECRET = "web-mail"
# Official python:3.12-slim, linux/amd64 manifest resolved on 2026-10-30.
# The isolated worker uses Alpine; the scientific web dependencies need glibc wheels.
WEB_IMAGE = "docker.io/library/python@sha256:1148dbb014615300fa7e713b2f94f550c0d1c69780c0805f84f093ceee34dd0b"


def bundle():
    files = list(APP.glob("*.py"))
    for folder in ("core", "runner", "static"):
        files += [p for p in (APP / folder).rglob("*") if p.is_file() and p.suffix in {".py", ".js", ".css", ".html", ".svg"}]
    files += list((APP / "prompts").glob("*.md"))
    files.append(APP / "deploy/web-requirements.lock")
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for path in sorted(files):
            data = path.read_bytes()
            info = tarfile.TarInfo(str(path.relative_to(ROOT)))
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            archive.addfile(info, io.BytesIO(data))
    data = gzip.compress(raw.getvalue(), mtime=0)
    if len(data) > 700_000:
        raise ValueError("Source bundle exceeds the ConfigMap safety bound.")
    return data, hashlib.sha256(data).hexdigest()


def private_settings(model_env: Path):
    existing = dict(dotenv_values(PRIVATE_ENV)) if PRIVATE_ENV.exists() else {}
    existing.setdefault("AUTOKAGGLE_ADMIN_ACCESS_CODE", secrets.token_urlsafe(36))
    existing["AUTOKAGGLE_PUBLIC_BASE_URL"] = "https://" + HOST
    if len(existing["AUTOKAGGLE_ADMIN_ACCESS_CODE"] or "") < 32:
        raise ValueError("The private administrator access code is missing or too short.")
    PRIVATE_ENV.parent.mkdir(parents=True, exist_ok=True)
    with PRIVATE_ENV.open("w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write("\n".join(k + "=" + v for k, v in existing.items() if v is not None) + "\n")
    model = dotenv_values(model_env)
    key = model.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("The selected private model file has no OpenRouter key.")
    return {"AUTOKAGGLE_ADMIN_ACCESS_CODE": existing["AUTOKAGGLE_ADMIN_ACCESS_CODE"], "OPENAI_API_KEY": key}


def manifest(kind, name, **body):
    api = {"Deployment": "apps/v1", "NetworkPolicy": "networking.k8s.io/v1", "Ingress": "networking.k8s.io/v1"}.get(kind, "v1")
    return {"apiVersion": api, "kind": kind, "metadata": {"name": name, "namespace": NAMESPACE}, **body}


def mail_settings(path: Path):
    values = dotenv_values(path)
    password = (values.get("AUTOKAGGLE_SMTP_PASSWORD") or "").replace(" ", "")
    if not password or values.get("AUTOKAGGLE_SMTP_HOST", "smtp.gmail.com") != "smtp.gmail.com" or str(values.get("AUTOKAGGLE_SMTP_PORT", "465")) != "465":
        raise ValueError("Configure a Gmail app password and SMTP over TLS on port 465.")
    sender = values.get("AUTOKAGGLE_MAIL_FROM") or "boldcoscientist@gmail.com"
    username = values.get("AUTOKAGGLE_SMTP_USERNAME") or sender
    if sender != "boldcoscientist@gmail.com" or username != sender:
        raise ValueError("Use the approved Gmail sender for this deployment.")
    return {"AUTOKAGGLE_MAIL_FROM": sender, "AUTOKAGGLE_SMTP_USERNAME": username,
            "AUTOKAGGLE_SMTP_PASSWORD": password, "AUTOKAGGLE_SMTP_HOST": "smtp.gmail.com", "AUTOKAGGLE_SMTP_PORT": "465"}


def gmail_settings(path: Path):
    info = json.loads(path.read_text())
    if (info.get("type") != "authorized_user"
            or info.get("scopes") != ["https://www.googleapis.com/auth/gmail.send"]
            or info.get("token_uri") != "https://oauth2.googleapis.com/token"
            or info.get("expected_sender") != "boldcoscientist@gmail.com"
            or not all(isinstance(info.get(k), str) and info[k] for k in ("client_id", "client_secret", "refresh_token"))):
        raise ValueError("Use the separate Gmail send-only credential created by configure_gmail.")
    return {"AUTOKAGGLE_MAIL_FROM": "boldcoscientist@gmail.com",
            **{"AUTOKAGGLE_GMAIL_" + k.upper(): info[k] for k in ("client_id", "client_secret", "refresh_token")}}


def mail_network_policy():
    # This policy selects only the trusted web service. Runner isolation is unchanged.
    return manifest("NetworkPolicy", "web-mail", spec={
        "podSelector": {"matchLabels": {"app": "autokaggle-web"}}, "policyTypes": ["Egress"],
        "egress": [{"to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8", "100.64.0.0/10"]}}],
                    "ports": [{"port": 465, "protocol": "TCP"}]}]})


def resources(source, digest, private, node_ips, mail=None, mail_enabled=False):
    source_name = "source-" + digest[:16]
    settings = {"AUTOKAGGLE_PRIVATE_MODE": "1", "AUTOKAGGLE_PUBLIC_BASE_URL": "https://" + HOST,
                "AUTOKAGGLE_ALLOWED_HOSTS": HOST, "AUTOKAGGLE_DATA_DIR": "/data/projects",
                "OPENAI_BASE_URL": "https://openrouter.ai/api/v1", "AUTOKAGGLE_MODEL": "openai/gpt-6.1-sol",
                "AUTOKAGGLE_MODE": "model", "PYTHONPATH": "/runtime:/app", "PYTHONDONTWRITEBYTECODE": "1",
                "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "HOME": "/tmp"}
    context = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
    shared = [{"name": "runtime", "mountPath": "/runtime"}, {"name": "app", "mountPath": "/app"},
              {"name": "tmp", "mountPath": "/tmp"}]
    init_source = ("import tarfile; "
                   "tarfile.open('/source/app.tar.gz').extractall('/app', filter='data')")
    # Install only pinned wheels. The source archive is authored by this deployer.
    init = {"name": "prepare-runtime", "image": WEB_IMAGE, "securityContext": context,
            "command": ["/bin/sh", "-ec"],
            "args": ["python -c \"" + init_source + "\"\n"
                     "python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: "
                     "--no-deps --target /runtime -r /app/autokaggle/deploy/web-requirements.lock"],
            "env": [{"name": "HOME", "value": "/tmp"}],
            "resources": {"requests": {"cpu": "500m", "memory": "512Mi"}, "limits": {"cpu": "2", "memory": "2Gi"}},
            "volumeMounts": shared + [{"name": "source", "mountPath": "/source", "readOnly": True}]}
    app = {"name": "web", "image": WEB_IMAGE, "securityContext": context,
           "workingDir": "/app", "command": ["python", "-m", "uvicorn", "autokaggle.app:create_app", "--factory",
             "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--no-proxy-headers"],
           "envFrom": [{"configMapRef": {"name": "web-config"}}, {"secretRef": {"name": "web-secrets"}},
                       {"secretRef": {"name": MAIL_SECRET, "optional": True}}],
           "ports": [{"name": "http", "containerPort": 8080}],
           "resources": {"requests": {"cpu": "500m", "memory": "1Gi"}, "limits": {"cpu": "4", "memory": "6Gi"}},
           "startupProbe": {"httpGet": {"path": "/healthz", "port": "http", "httpHeaders": [{"name": "Host", "value": HOST}]}, "periodSeconds": 5, "failureThreshold": 36},
           "readinessProbe": {"httpGet": {"path": "/healthz", "port": "http", "httpHeaders": [{"name": "Host", "value": HOST}]}, "periodSeconds": 10},
           "volumeMounts": [{**v, "readOnly": v["name"] != "tmp"} for v in shared] + [{"name": "data", "mountPath": "/data"}]}
    pod = {"automountServiceAccountToken": False, "enableServiceLinks": False, "serviceAccountName": "web-no-access",
           "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000, "fsGroup": 1000,
                               "fsGroupChangePolicy": "OnRootMismatch", "seccompProfile": {"type": "RuntimeDefault"}},
           "initContainers": [init], "containers": [app],
           "volumes": [{"name": "source", "configMap": {"name": source_name}}, {"name": "runtime", "emptyDir": {"sizeLimit": "2Gi"}},
                       {"name": "app", "emptyDir": {"sizeLimit": "20Mi"}}, {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}},
                       {"name": "data", "persistentVolumeClaim": {"claimName": "web-data"}}]}
    items = [
      manifest("ServiceAccount", "web-no-access", automountServiceAccountToken=False),
      manifest("PersistentVolumeClaim", "web-data", spec={"accessModes": ["ReadWriteOnce"], "storageClassName": "civo-volume", "resources": {"requests": {"storage": "10Gi"}}}),
      manifest("ConfigMap", source_name, immutable=True, binaryData={"app.tar.gz": base64.b64encode(source).decode()}),
      manifest("ConfigMap", "web-config", data=settings),
      manifest("Secret", "web-secrets", type="Opaque", stringData=private),
      manifest("NetworkPolicy", "web-boundary", spec={"podSelector": {"matchLabels": {"app": "autokaggle-web"}}, "policyTypes": ["Ingress", "Egress"],
        "ingress": [{"from": [{"ipBlock": {"cidr": ip + "/32"}} for ip in node_ips], "ports": [{"protocol": "TCP", "port": 8080}]}],
        "egress": [{"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}], "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}]},
                   {"to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8", "100.64.0.0/10"]}}], "ports": [{"port": 443, "protocol": "TCP"}]}]}),
      manifest("Deployment", "web", spec={"replicas": 1, "strategy": {"type": "Recreate"}, "selector": {"matchLabels": {"app": "autokaggle-web"}},
        "template": {"metadata": {"labels": {"app": "autokaggle-web"}, "annotations": {"autokaggle/source-sha256": digest,
             "autokaggle/settings-sha256": hashlib.sha256(json.dumps({**settings, **private, **(mail or {})}, sort_keys=True).encode()).hexdigest()}}, "spec": pod}}),
      manifest("Service", "web", spec={"selector": {"app": "autokaggle-web"}, "ports": [{"name": "http", "port": 8080, "targetPort": "http"}]}),
    ]
    if mail is not None:
        items.insert(0, manifest("Secret", MAIL_SECRET, type="Opaque", stringData=mail))
    if (mail is not None and "AUTOKAGGLE_SMTP_PASSWORD" in mail) or (mail is None and mail_enabled):
        items.insert(0, mail_network_policy())
    return items


def ingress():
    item = manifest("Ingress", "web", spec={"tls": [{"hosts": [HOST], "secretName": "autokaggle-web-tls"}],
       "rules": [{"host": HOST, "http": {"paths": [{"path": "/", "pathType": "Prefix", "backend": {"service": {"name": "web", "port": {"name": "http"}}}}]}}]})
    item["metadata"]["annotations"] = {"kubernetes.io/ingress.class": "traefik", "traefik.ingress.kubernetes.io/router.entrypoints": "websecure", "traefik.ingress.kubernetes.io/router.tls": "true"}
    return item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["deploy", "expose", "status"])
    parser.add_argument("--model-env", type=Path, default=ROOT / ".env")
    parser.add_argument("--mail-env", type=Path, help="Private Gmail app-password file. Existing hosted mail settings are preserved when omitted.")
    parser.add_argument("--gmail-credentials", type=Path, help="Private Gmail send-only OAuth JSON. Uses HTTPS, which Civo permits.")
    args = parser.parse_args()
    with private_kubeconfig() as config:
        kube = Kubectl(config)
        if args.command == "deploy":
            source, digest = bundle()
            private = private_settings(args.model_env)
            if args.mail_env and args.gmail_credentials:
                raise ValueError("Choose Gmail HTTPS credentials or SMTP settings, not both.")
            mail = gmail_settings(args.gmail_credentials) if args.gmail_credentials else mail_settings(args.mail_env) if args.mail_env else None
            nodes = kube.json("get", "nodes")["items"]
            addresses = sorted({a["address"] for n in nodes for a in n["status"]["addresses"] if a["type"] in {"InternalIP", "ExternalIP"} and ":" not in a["address"]})
            for item in resources(source, digest, private, addresses, mail):
                if item["kind"] == "Secret":
                    kube.run("apply", "--server-side", "--field-manager=autokaggle-web", "-f", "-", document=item)
                else:
                    kube.run("apply", "-f", "-", document=item)
            if args.gmail_credentials:
                kube.run("delete", "networkpolicy", "web-mail", "-n", NAMESPACE, "--ignore-not-found")
            print(json.dumps({"namespace": NAMESPACE, "source_sha256": digest, "source_bytes": len(source), "host": HOST, "exposed": False}))
        elif args.command == "expose":
            cert = kube.json("get", "certificate", "autokaggle-web-tls", "-n", NAMESPACE)
            if not any(c.get("type") == "Ready" and c.get("status") == "True" for c in cert.get("status", {}).get("conditions", [])):
                raise RuntimeError("The HTTPS certificate is not ready.")
            deployment = kube.json("get", "deployment", "web", "-n", NAMESPACE)
            if deployment.get("status", {}).get("availableReplicas", 0) < 1:
                raise RuntimeError("The private web deployment is not available.")
            kube.run("apply", "-f", "-", document=ingress())
            print("Private review service exposed at https://" + HOST)
        else:
            for kind in ("deployment", "pods", "pvc", "ingress", "certificate"):
                print(kube.run("get", kind, "-n", NAMESPACE))


if __name__ == "__main__":
    main()
