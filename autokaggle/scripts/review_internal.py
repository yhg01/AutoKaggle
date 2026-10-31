"""Read-only Civo snapshots, optional live model capture, and loopback review QA.

No release, pod update, account change, or production project write is performed.
Credentials stay in kubectl's configuration and the existing server environment.
Preview data and receipts are written only under ignored autokaggle/test-results.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def fetch(args):
    sources = {name: (ROOT / "autokaggle" / (name + ".py")).read_text(encoding="utf-8")
               for name in ("observability", "conversation")}
    payload = json.dumps({"sources": sources, "live_model": args.live_model})
    # The supplied text is trusted application source, never participant code.
    remote = r'''
import json, sqlite3, sys, types
from pathlib import Path
import autokaggle
payload=json.loads(sys.stdin.readline())
def load(name):
    full='autokaggle.'+name
    module=types.ModuleType(full); module.__package__='autokaggle'; module.__file__='/app/autokaggle/'+name+'.py'
    sys.modules[full]=module; setattr(autokaggle,name,module)
    exec(compile(payload['sources'][name],module.__file__,'exec'),module.__dict__)
    return module
obs=load('observability'); conversation=load('conversation')
class ReadStore:
    def connection(self):
        return sqlite3.connect('file:/data/projects/projects.sqlite3?mode=ro',uri=True)
store=ReadStore(); snapshots=[]
with store.connection() as con:
    items=[json.loads(r[0]) for r in con.execute('select body from projects order by updated_at desc')]
for p in items:
    snapshots.append({'project':obs.project_detail(p),'review':obs.review_data(store,p),'trace_limit':obs.LIMIT,
        'reasoning_note':'Only provider-returned readable reasoning is available.'})
receipt={'live_model_requested':payload['live_model'],'production_projects_written':False,'snapshots':len(snapshots)}
if payload['live_model']:
    import os
    assert os.environ.get('OPENAI_BASE_URL','').startswith('https://openrouter.ai/'), 'OpenRouter must be configured.'
    p={'id':'1cf5b8a7-4f74-4e22-bb9c-911422d51600','title':'Internal review capture validation','brief':'Synthetic small fixture',
       'answers':{},'design':{},'revision':1,'status':'draft','created_at':'2026-10-31T00:00:00+00:00','updated_at':'2026-10-31T00:00:00+00:00','_model_calls':0}
    conversation.submit_message(p,'Predict binary battery failure from temperature and age. The task is an offline prediction comparison.','review-live-capture')
    traces=p.get('_model_traces',[])
    receipt.update(model=os.environ.get('AUTOKAGGLE_MODEL'),call_count=len(traces),conversation_status=p['conversation']['status'],
        calls=[{'provider':t.get('provider_status'),'validation':t.get('validation'),'trigger':t.get('trigger'),
                'usage':t.get('usage'),'duration_ms':t.get('duration_ms')} for t in traces])
    assert traces and all(t.get('provider_status')=='completed' for t in traces), 'Live provider call failed.'
    assert any(t.get('validation',{}).get('status')=='accepted' for t in traces), 'Application did not accept a live response.'
    assert all(t.get('trigger',{}).get('message_id') for t in traces), 'Trigger links were not captured.'
    snapshots.insert(0,{'project':obs.project_detail(p),'review':obs.review_data(store,p),'trace_limit':obs.LIMIT})
print(json.dumps(obs.scrub({'snapshots':snapshots,'receipt':receipt}),ensure_ascii=True))
'''
    # Code and payload are a single script on stdin; no keys or source in argv.
    import base64
    script = "import io, sys, base64\nsys.stdin=io.StringIO(base64.b64decode('" + base64.b64encode((payload + "\n").encode()).decode() + "').decode())\n" + remote
    result = subprocess.run([str(args.kubectl), "--kubeconfig", str(args.kubeconfig), "--request-timeout=30s",
        "-n", "autokaggle-web", "exec", "-i", "deployment/web", "-c", "web", "--", "python", "-"],
        input=script, text=True, encoding="utf-8", capture_output=True, timeout=300)
    if result.returncode:
        raise RuntimeError("Read-only remote review validation failed; no release was performed.")
    return json.loads(result.stdout)


def serve(result, output, port):
    from fastapi.responses import RedirectResponse
    from autokaggle.access import ADMIN_COOKIE, SESSION_SECONDS
    from autokaggle.app import create_app
    import uvicorn
    os.environ.update(AUTOKAGGLE_PRIVATE_MODE="1", AUTOKAGGLE_ADMIN_ACCESS_CODE="local-review-preview-only-" + "x" * 36,
                      AUTOKAGGLE_PUBLIC_BASE_URL=f"http://127.0.0.1:{port}", AUTOKAGGLE_MODE="rules")
    app = create_app(output / "preview-data")
    for snapshot in result["snapshots"]:
        p = snapshot["project"]
        with app.state.store.connection() as con:
            con.execute("INSERT OR REPLACE INTO projects (id,owner,updated_at,participant,body) VALUES (?,?,?,NULL,?)",
                        (p["id"], "preview-data-owner", p["updated_at"], json.dumps(p)))
    @app.get("/__preview")
    def preview_login():
        import hashlib, secrets, time
        from autokaggle.email_auth import USER_COOKIE, USER_SESSION_SECONDS
        token = secrets.token_urlsafe(32)
        owner = "account_local_review_preview_xxxxxxxxxxxxxxxxxxxxxxxx"
        with app.state.store.connection() as con:
            con.execute("INSERT OR IGNORE INTO email_accounts VALUES (?,?,?)", (owner, "preview@example.invalid", time.time()))
            con.execute("INSERT INTO email_sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), owner, time.time() + USER_SESSION_SECONDS))
        first = result["snapshots"][0]["project"]["id"]
        response = RedirectResponse("/internal?project=" + first + "&view=calls", status_code=303)
        response.set_cookie(USER_COOKIE, token, httponly=True, samesite="strict")
        response.set_cookie(ADMIN_COOKIE, app.state.access._sign("admin:" + owner, SESSION_SECONDS), httponly=True, samesite="strict")
        return response
    print(f"Local preview: http://127.0.0.1:{port}/__preview", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--kubeconfig", type=Path)
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--reuse-snapshot", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    output = ROOT / "autokaggle/test-results/internal-review"
    output.mkdir(parents=True, exist_ok=True)
    if args.reuse_snapshot:
        result = json.loads((output / "snapshot.json").read_text(encoding="utf-8"))
    else:
        if not args.kubectl or not args.kubeconfig:
            parser.error("--kubectl and --kubeconfig are required unless reusing a snapshot")
        result = fetch(args)
        (output / "snapshot.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        (output / "live-receipt.json").write_text(json.dumps(result["receipt"], indent=2), encoding="utf-8")
    print(json.dumps(result["receipt"], ensure_ascii=False), flush=True)
    if args.serve:
        serve(result, output, args.port)


if __name__ == "__main__":
    main()
