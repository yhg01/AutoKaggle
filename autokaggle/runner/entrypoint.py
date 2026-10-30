"""Fixed prediction entrypoint. Not an isolation boundary or a scorer.

Only run after the cluster sandbox is approved. The trusted controller must
validate predictions outside this pod; no pod output is authoritative.
"""
from pathlib import Path
import os
import resource
import selectors
import signal
import subprocess
import time

MAX_LOG = 64 * 1024
MAX_OUTPUT = 5_000_000


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    process = subprocess.Popen(
        ["/usr/local/bin/python", "-I", "-B", "/submission/main.py", "--input", "/input/test_features.csv", "--output", "/output/predictions.csv"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/scratch", "TMPDIR": "/scratch", "OMP_NUM_THREADS": "1",
             "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"},
        cwd="/scratch", start_new_session=True, preexec_fn=_limits,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    total = 0
    deadline = time.monotonic() + 100
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise RuntimeError("Prediction time limit exceeded.")
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > MAX_LOG:
                    raise RuntimeError("Prediction log limit exceeded.")
                # Never write raw worker output to cluster logs or a user response.
        code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        output = Path("/output/predictions.csv")
        if code != 0 or output.is_symlink() or not output.is_file() or output.stat().st_size > MAX_OUTPUT:
            raise RuntimeError("Prediction did not produce an acceptable output artifact.")
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        selector.close()
        process.stdout.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Neither exception text nor tracebacks may expose hidden inputs.
        raise SystemExit(1) from None
