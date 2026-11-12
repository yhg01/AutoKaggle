"""Deploy the internal Lite service beside Full on the existing Civo cluster.

The service has its own host, credentials, source, database, and persistent claim.
It reuses the existing ingress, TLS issuer, and approved Gmail sender. It does
not change the Full Deployment, its data, or its credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

from dotenv import dotenv_values

from . import web
from .probe_cluster import Kubectl, private_kubeconfig

HOST = "lite." + web.HOST
BASE_URL = "https://" + HOST
PRIVATE_ENV = Path.home() / ".config/autokaggle/lite-web.env"
GITHUB_ENV = Path.home() / ".config/autokaggle/lite-github.env"
MEMBERS = "boldcoscientist@gmail.com"


def github_settings():
    """The optional GitHub token for evaluator publishing, read from its own private file. It enters only the Secret."""
    token = (dotenv_values(GITHUB_ENV).get("AUTOKAGGLE_LITE_GITHUB_TOKEN") or "").strip() if GITHUB_ENV.exists() else ""
    if token and not re.fullmatch(r"[A-Za-z0-9_]{20,255}", token):
        raise ValueError("The private GitHub file must hold one token in AUTOKAGGLE_LITE_GITHUB_TOKEN.")
    return {"AUTOKAGGLE_LITE_GITHUB_TOKEN": token} if token else {}


def private_settings(model_env: Path):
    model = dotenv_values(model_env)
    key = model.get("DEEPSEEK_API_KEY") or model.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("The private model file must contain DEEPSEEK_API_KEY or OPENROUTER_API_KEY.")
    saved = dotenv_values(PRIVATE_ENV) if PRIVATE_ENV.exists() else {}
    admin = saved.get("AUTOKAGGLE_ADMIN_ACCESS_CODE") or secrets.token_urlsafe(36)
    if not 32 <= len(admin) <= 1024:
        raise ValueError("The Lite administrator key is invalid.")
    PRIVATE_ENV.parent.mkdir(parents=True, exist_ok=True)
    with PRIVATE_ENV.open("w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write("AUTOKAGGLE_ADMIN_ACCESS_CODE=" + admin + "\n")
        handle.write("AUTOKAGGLE_PUBLIC_BASE_URL=" + BASE_URL + "\n")
    return {"AUTOKAGGLE_ADMIN_ACCESS_CODE": admin, "OPENAI_API_KEY": key,
            **({"DEEPSEEK_API_KEY": key} if model.get("DEEPSEEK_API_KEY") else {"OPENROUTER_API_KEY": key}), **github_settings()}


def resources(source, digest, private, node_ips, *, members=MEMBERS, github_owner="", access_policy="members"):
    if access_policy not in {"members", "verified_email"}:
        raise ValueError("Invalid Lite access policy.")
    if github_owner and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", github_owner):
        raise ValueError("The GitHub owner must be one account or organization name.")
    names = {
        web.HOST: HOST, "web-no-access": "lite-no-access", "web-data": "lite-data",
        "source-" + digest[:16]: "lite-source-" + digest[:16],
        "web-config": "lite-config", "web-secrets": "lite-secrets",
        "web-boundary": "lite-boundary", "autokaggle-web": "autokaggle-lite",
        "web": "lite",
    }

    def rename(value):
        if isinstance(value, dict):
            return {key: rename(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rename(item) for item in value]
        if isinstance(value, str):
            return names.get(value, value)
        return value

    items = rename(web.resources(source, digest, private, node_ips))
    for item in items:
        # Namespace is shared only to reuse the installed issuer and mail Secret.
        item["metadata"]["namespace"] = web.NAMESPACE
        if item["kind"] == "PersistentVolumeClaim":
            item["spec"]["resources"]["requests"]["storage"] = "10Gi"
        if item["kind"] == "ConfigMap" and item["metadata"]["name"] == "lite-config":
            item["data"]["AUTOKAGGLE_PUBLIC_BASE_URL"] = BASE_URL
            item["data"]["AUTOKAGGLE_LITE_MEMBERS"] = members
            item["data"]["AUTOKAGGLE_LITE_ACCESS_POLICY"] = access_policy
            item["data"]["AUTOKAGGLE_DEFAULT_INTERFACE"] = "lite"
            item["data"]["AUTOKAGGLE_WORKERS"] = "5"
            if github_owner:
                item["data"]["AUTOKAGGLE_LITE_GITHUB_OWNER"] = github_owner
        if item["kind"] == "Deployment":
            pod = item["spec"]["template"]["spec"]
            pod["containers"][0]["resources"] = {
                "requests": {"cpu": "250m", "memory": "512Mi"},
                "limits": {"cpu": "2", "memory": "2Gi"},
            }
            item["spec"]["template"]["metadata"]["annotations"]["autokaggle/settings-sha256"] = hashlib.sha256(
                json.dumps({"private": private, "host": HOST, "members": members, "workers": 5, "github_owner": github_owner}, sort_keys=True).encode()
            ).hexdigest()
    return items


def certificate_resource():
    return {
        "apiVersion": "cert-manager.io/v1", "kind": "Certificate",
        "metadata": {"name": "autokaggle-lite-tls", "namespace": web.NAMESPACE},
        "spec": {"dnsNames": [HOST], "issuerRef": {"kind": "Issuer", "name": "autokaggle-letsencrypt"},
                 "privateKey": {"algorithm": "ECDSA", "rotationPolicy": "Always", "size": 256},
                 "renewBefore": "360h", "secretName": "autokaggle-lite-tls"},
    }


def route_resources():
    ingress = web.ingress()
    ingress["metadata"]["name"] = "lite"
    ingress["spec"]["tls"] = [{"hosts": [HOST], "secretName": "autokaggle-lite-tls"}]
    ingress["spec"]["rules"][0]["host"] = HOST
    ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]["name"] = "lite"
    return [ingress]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["tls", "deploy", "expose", "status"])
    parser.add_argument("--model-env", type=Path, default=web.ROOT / ".env")
    parser.add_argument("--members", help="Approved lab emails, comma separated. Existing membership is preserved when omitted.")
    parser.add_argument("--access-policy", choices=["members", "verified_email"], help="Preserve the existing policy when omitted.")
    parser.add_argument("--github-owner", help="Account or organization for evaluator repositories. Preserved when omitted. An empty value turns publishing off.")
    args = parser.parse_args()
    with private_kubeconfig() as config:
        kube = Kubectl(config)
        if args.command == "tls":
            kube.run("apply", "--server-side", "--field-manager=autokaggle-lite", "-f", "-", document=certificate_resource())
            print("Requested the Lite certificate from the existing issuer.")
        elif args.command == "deploy":
            source, digest = web.bundle()
            private = private_settings(args.model_env)
            nodes = kube.json("get", "nodes")["items"]
            addresses = sorted({a["address"] for n in nodes for a in n["status"]["addresses"]
                                if a["type"] in {"InternalIP", "ExternalIP"} and ":" not in a["address"]})
            configs = kube.json("get", "configmaps", "-n", web.NAMESPACE)["items"]
            prior = next((x.get("data", {}) for x in configs if x["metadata"]["name"] == "lite-config"), {})
            members = args.members if args.members is not None else prior.get("AUTOKAGGLE_LITE_MEMBERS", MEMBERS)
            policy = args.access_policy if args.access_policy is not None else prior.get("AUTOKAGGLE_LITE_ACCESS_POLICY", "members")
            owner = args.github_owner if args.github_owner is not None else prior.get("AUTOKAGGLE_LITE_GITHUB_OWNER", "")
            if not owner:  # Without an owner publishing is off. Keep an unused credential off the cluster.
                private.pop("AUTOKAGGLE_LITE_GITHUB_TOKEN", None)
            for item in resources(source, digest, private, addresses, members=members, github_owner=owner, access_policy=policy):
                kube.run("apply", "--server-side", "--field-manager=autokaggle-lite", "-f", "-", document=item)
            print(json.dumps({"host": HOST, "source_sha256": digest, "source_bytes": len(source), "github_owner": owner or None,
                              "github_token": "AUTOKAGGLE_LITE_GITHUB_TOKEN" in private}))
        elif args.command == "expose":
            cert = kube.json("get", "certificate", "autokaggle-lite-tls", "-n", web.NAMESPACE)
            if not any(x.get("type") == "Ready" and x.get("status") == "True"
                       for x in cert.get("status", {}).get("conditions", [])):
                raise RuntimeError("The Lite certificate is not ready.")
            deployment = kube.json("get", "deployment", "lite", "-n", web.NAMESPACE)
            if deployment.get("status", {}).get("availableReplicas", 0) < 1:
                raise RuntimeError("The Lite deployment is not ready.")
            for item in route_resources():
                kube.run("apply", "--server-side", "--field-manager=autokaggle-lite", "-f", "-", document=item)
            print(BASE_URL + "/lite")
        else:
            for kind, name in [("deployment", "lite"), ("pvc", "lite-data"), ("certificate", "autokaggle-lite-tls")]:
                print(kube.run("get", kind, name, "-n", web.NAMESPACE))


if __name__ == "__main__":
    main()
