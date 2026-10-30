# Private review HTTPS

The TLS setup uses only the AutoKaggle cluster in `lon1`, ID `ecc962fa-2f4c-4a3f-96c4-179af273fb7a`. Its hostname is `ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com`. The existing Traefik controller listens on ports 80 and 443. The setup does not create an app route.

Run these commands from the repository root with the project Python environment active:

```sh
python autokaggle/deploy/web-tls.py all
python autokaggle/deploy/web-tls.py verify
```

The operator needs Civo credentials, `civo`, `kubectl`, `openssl`, and the Python `certifi` package. The script gets a temporary kubeconfig with mode `0600` and removes it when the command ends. It does not change the current Kubernetes context.

The `all` command installs the official cert-manager `v1.21.3` manifest. It checks the pinned SHA-256 before application. If another cert-manager version already exists, the script stops for inspection. It then applies [web-tls.yaml](web-tls.yaml), which contains:

- The `autokaggle-web` namespace with restricted Pod Security for Kubernetes 1.35.
- The namespaced `autokaggle-letsencrypt` Issuer. Its ACME contact is `boldcoscientist@gmail.com`.
- The `autokaggle-web-tls` Certificate and target Secret for the Civo hostname.

The Issuer uses HTTP-01 through the existing Traefik controller. The solver uses a ClusterIP Service and a pod security context compatible with the restricted policy. The class annotation is used because the installed Traefik configuration has no IngressClass object. The setup keeps this configuration intact.

Network policies must allow the host-network Traefik controller to reach solver pods on TCP port 8089. Solver pods have the label `app.kubernetes.io/component=autokaggle-acme-solver`. Keep this route available for renewal. The HTTP solver route exists only while an ACME challenge is active.

The `verify` command checks Certificate readiness. It retrieves only the public certificate chain and checks the chain and hostname with the local trusted CA bundle. It writes web-tls.verification.json (local operational record; not included in this repository). It does not read or print the certificate private key. This report checks the issued certificate; a separate app deployment check must verify the certificate served on port 443.

The app Ingress must reference `autokaggle-web-tls` in the same namespace. Use the `websecure` entry point and the Civo hostname. The app service, private access controls, storage, and model workflow are managed separately. The TLS setup does not change the `autokaggle-runs` policies or the original Co-Scientist cluster.

Sources: [official cert-manager installation](https://cert-manager.io/docs/installation/kubectl/), [supported Kubernetes versions](https://cert-manager.io/docs/releases/), [HTTP-01 solver configuration](https://cert-manager.io/docs/configuration/acme/http01/).
