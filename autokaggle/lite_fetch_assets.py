"""Download the assets declared in assets.json and verify each SHA-256. Standard library only.

    python fetch_assets.py

Assets are stored under assets/. A file that already matches is kept.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def download(url, partial, limit):
    """Write the URL to a file and return (size, sha256). Certificates are always verified.

    Some Python installations have no certificate store. In that case this uses the certificate
    bundle shipped with pip, then the system curl. The SHA-256 check applies to every route.
    """
    contexts = [None]
    try:
        from pip._vendor import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    request = urllib.request.Request(url, headers={"User-Agent": "lite-evaluator-assets"})
    for context in contexts:
        try:
            value, size = hashlib.sha256(), 0
            with urllib.request.urlopen(request, timeout=120, context=context) as response, partial.open("wb") as stream:
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(block)
                    if size > limit:
                        raise ValueError("larger than its declared size")
                    value.update(block)
                    stream.write(block)
            return size, value.hexdigest()
        except urllib.error.URLError as exc:
            if not isinstance(exc.reason, ssl.SSLError):
                raise
    if not shutil.which("curl"):
        raise OSError("this Python has no usable certificate store. Install its certificates, or place the verified file under assets/ yourself.")
    done = subprocess.run(["curl", "-fsSL", "--proto", "=https", "--max-filesize", str(limit), "-o", str(partial), url],
                          capture_output=True, text=True, timeout=3600)
    if done.returncode:
        raise OSError("this Python has no usable certificate store, and curl failed: " + done.stderr.strip()[-200:])
    return partial.stat().st_size, digest(partial)


def main():
    assets = json.loads((ROOT / "assets.json").read_text())
    failed = False
    for asset in assets:
        target = (ROOT / asset["path"]).resolve()
        if ROOT / "assets" not in target.parents or not asset["url"].startswith("https://"):
            print(f"fetch_assets: {asset['path']} is not an acceptable asset declaration.", file=sys.stderr)
            failed = True
            continue
        if target.is_file() and digest(target) == asset["sha256"]:
            print(f"present   {asset['path']}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        try:
            size, value = download(asset["url"], partial, asset["bytes"])
            if size != asset["bytes"] or value != asset["sha256"]:
                raise ValueError("content does not match the declared size and SHA-256")
            os.replace(partial, target)
            print(f"retrieved {asset['path']}")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            partial.unlink(missing_ok=True)
            print(f"fetch_assets: {asset['path']} from {asset['url']}: {exc}", file=sys.stderr)
            failed = True
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
