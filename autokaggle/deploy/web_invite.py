"""Create a private review link without sending email.

Only an operator with Civo cluster access can use this helper. The recipient
receives the existing single-use, project-scoped invitation flow. The link is
written to an owner-only file and is never printed.
"""
import argparse
import os
from pathlib import Path
import subprocess
import uuid

from .probe_cluster import private_kubeconfig
from .web import HOST, NAMESPACE

REMOTE = """
import hashlib,json,secrets,sys
from datetime import timedelta
from pathlib import Path
from autokaggle.store import Store
from autokaggle import notifications,workflow
store=Store(Path('/data/projects'))
notifications.initialize(store)
with store.connection() as connection:
    connection.execute('BEGIN IMMEDIATE')
    row=connection.execute('SELECT body FROM projects WHERE id=?',(sys.argv[1],)).fetchone()
    if not row:
        raise SystemExit('The challenge does not exist.')
    project=json.loads(row[0]); current=workflow.view(project)
    if current['status']!='ready_for_review':
        raise SystemExit('The challenge must pass its build checks before invitation.')
    token=secrets.token_urlsafe(32)
    connection.execute('INSERT INTO review_tokens (digest,project,version,expires,used,draft) VALUES (?,?,?,?,0,?)',
        (hashlib.sha256(token.encode()).hexdigest(),project['id'],current['version'],
        (notifications._utc()+timedelta(hours=24)).isoformat(),workflow.fingerprint(project)))
print(token)
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_id', type=uuid.UUID)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise SystemExit('Choose a new private output file; the existing file was not changed.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with private_kubeconfig() as config:
        result=subprocess.run(['kubectl','--kubeconfig',config,'exec','-n',NAMESPACE,'deployment/web','-c','web',
                               '--','python','-c',REMOTE,str(args.project_id)],capture_output=True,text=True,timeout=60)
    if result.returncode:
        raise SystemExit('The invitation could not be created. Check challenge readiness and service availability.')
    token=result.stdout.strip()
    if len(token)!=43 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in token):
        raise SystemExit('The service returned an invalid invitation.')
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as target:
        target.write('https://'+HOST+'/review#token='+token+'\n')
    print('Private review link saved. It expires in 24 hours and works once. No email was sent.')


if __name__=='__main__':
    main()
