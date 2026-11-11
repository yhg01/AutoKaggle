# Disposable runtime for Lite evaluator builds and clean-clone scoring tests.
# It holds no application, publishing, or provider credentials.
FROM python:3.12-slim-bookworm

ARG OPENCODE_VERSION=1.19.5
ARG TARGETARCH
ARG UID=1000
ARG GID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# The pinned coding agent, from the official npm registry package for this architecture.
RUN set -eu; \
    case "${TARGETARCH}" in amd64) arch=x64 ;; arm64) arch=arm64 ;; *) echo "unsupported architecture ${TARGETARCH}" >&2; exit 1 ;; esac; \
    curl -fsSL "https://registry.npmjs.org/opencode-linux-${arch}/-/opencode-linux-${arch}-${OPENCODE_VERSION}.tgz" -o /tmp/opencode.tgz; \
    mkdir /tmp/opencode && tar -xzf /tmp/opencode.tgz -C /tmp/opencode; \
    install -m 0755 /tmp/opencode/package/bin/opencode /usr/local/bin/opencode; \
    rm -rf /tmp/opencode /tmp/opencode.tgz; \
    opencode --version

RUN groupadd --gid "${GID}" myuser 2>/dev/null || true; \
    useradd --uid "${UID}" --gid "${GID}" --create-home --shell /bin/bash myuser 2>/dev/null || true

USER myuser
WORKDIR /mnt/work
