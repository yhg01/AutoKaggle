"""Exercise the real local HTTP server through curl. Synthetic data only."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8877")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="autokaggle-http-") as directory:
        work = Path(directory)
        cookie = work / "session.cookies"
        def call(method, path, body=None, file=None, anonymous=False, expected=200):
            cmd = ["curl", "--silent", "--show-error", "--max-time", "150", "-X", method, "-w", "\n%{http_code}", args.base + path]
            if not anonymous:
                cmd += ["-b", str(cookie), "-c", str(cookie)]
            if body is not None:
                body_path = work / "body.json"
                body_path.write_text(json.dumps(body))
                cmd += ["-H", "Content-Type: application/json", "--data-binary", "@" + str(body_path)]
            if file:
                cmd += ["-F", "file=@" + str(file)]
            raw = subprocess.check_output(cmd)
            data, code = raw.rsplit(b"\n", 1)
            assert int(code) == expected, (method, path, code, data[:300])
            try:
                return json.loads(data)
            except (ValueError, UnicodeDecodeError):
                return data
        config = call("GET", "/api/config")
        project = call("POST", "/api/projects", {"title": "HTTP validation"})
        route = "/api/projects/" + project["id"]
        project = call("POST", route + "/example", {"name": "materials"})
        project = call("POST", route + "/analyze")
        assert project["analysis"]["summary"]["blockers"] == 0
        first = call("POST", route + "/prepare", {"acknowledge_review": True})
        public = call("GET", route + "/download/researcher")
        private = call("GET", route + "/download/organizer")
        pzip, oz = zipfile.ZipFile(io.BytesIO(public)), zipfile.ZipFile(io.BytesIO(private))
        assert "test.csv" not in pzip.namelist() and "test.csv" in oz.namelist()
        token = call("GET", route + "/participant-link")["url"].rsplit("/", 1)[1]
        participant = call("GET", f"/api/challenges/{token}", anonymous=True)
        assert call("GET", participant["download_url"], anonymous=True) == public
        call("GET", route + "/download/organizer", anonymous=True, expected=404)
        call("PATCH", route, {"answers": {"labels_public": "yes"}})
        call("GET", f"/api/challenges/{token}", anonymous=True, expected=404)
        blocked = call("POST", route + "/analyze")
        assert any(c["id"] == "public_labels" and c["severity"] == "blocker" for c in blocked["analysis"]["checks"])
        call("POST", route + "/prepare", {"acknowledge_review": True}, expected=422)
        call("PATCH", route, {"answers": {"labels_public": "no"}})
        sample = work / "replacement.csv"
        sample.write_bytes(pzip.read("train.csv"))
        uploaded = call("POST", route + "/dataset", file=sample)
        assert uploaded["dataset"]["rows"] == 480
        # A malformed replacement does not destroy the accepted data.
        sample.write_text("x,x\n1,2\n")
        call("POST", route + "/dataset", file=sample, expected=422)
        assert call("GET", route)["dataset"]["rows"] == 480
        report = {"server": args.base, "mode": config["mode"], "train_rows": first["prepared"]["train_rows"],
            "test_rows": first["prepared"]["test_rows"], "checks": ["real curl create", "data audit", "training-only baseline", "package generation", "participant training download", "private download denied", "edit invalidates participant link", "public labels block preparation", "CSV replacement", "invalid upload preserves work"],
            "researcher_files": pzip.namelist(), "organizer_files": oz.namelist()}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
