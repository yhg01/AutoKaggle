#!/bin/sh
# Local operator wrapper. The Python installer checks the exact cluster and node.
set -eu
case "${1:-}" in
  --help)
    cat <<'EOF'
Usage: install-gvisor-node.sh --install

Run from the repository root with the project Python environment active.
This installs the pinned, checksum-verified gVisor release on the designated
AutoKaggle worker. It saves private backups and refuses existing custom files.
It does not restart k3s. Run the separate provider activation and acceptance
steps described in deploy/README.md. No participant code is executed here.
EOF
    ;;
  --install)
    [ "$#" -eq 1 ] || exit 2
    exec python3 -m autokaggle.deploy.install_runtime
    ;;
  *) printf '%s\n' 'Use --help or --install.' >&2; exit 2 ;;
esac
