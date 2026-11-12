"""Update existing Full/Lite source and model settings without replacing runtime add-ons.

Use private files for credentials. This command preserves the deployment's access
settings, extra mounts, and database. It creates a SQLite backup before restart.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
from dotenv import dotenv_values
from . import web, lite_jobs
from .probe_cluster import private_kubeconfig, Kubectl


def update(kube, service, source, digest, model, *, build_image=None, github_owner=None, github_token=None):
    namespace=web.NAMESPACE
    deployment=kube.json('get','deployment',service,'-n',namespace)
    pod=deployment['spec']['template']['spec']
    label=deployment['spec']['selector']['matchLabels']['app']
    pods=kube.json('get','pods','-n',namespace,'-l','app='+label)['items']
    running=next(p['metadata']['name'] for p in pods if p['status']['phase']=='Running' and not p['metadata'].get('deletionTimestamp'))
    # The backup remains private on the same persistent volume. Never print project bodies.
    backup="""import sqlite3,json,pathlib,hashlib,time
p=pathlib.Path('/data/projects/projects.sqlite3');c=sqlite3.connect(p)
rows=c.execute('select id,body from projects').fetchall()
active=[]
for i,b in rows:
 d=json.loads(b)
 for key in ('conversation','lite','onboarding'):
  if d.get(key,{}).get('status') in ('working','running'):active.append(i)
 if any(b.get('status') in ('queued','building','testing') for b in d.get('lite_evaluator',{}).get('builds',[])):active.append(i)
if active:raise SystemExit('Active project jobs: retry after they finish.')
target=p.parent/('backup-'+time.strftime('%Y%m%d-%H%M%S')+'.sqlite3')
c.backup(sqlite3.connect(target));target.chmod(0o600)
print(json.dumps({'projects':len(rows),'backup':target.name,'bodies_sha256':hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest()}))
"""
    evidence=json.loads(kube.run('exec','-n',namespace,running,'--','python','-c',backup))
    name=('lite-source-' if service=='lite' else 'source-')+digest[:16]
    kube.run('apply','--server-side','--field-manager=autokaggle-rollout','-f','-',document=web.manifest('ConfigMap',name,immutable=True,binaryData={'app.tar.gz':base64.b64encode(source).decode()}))
    key=model['DEEPSEEK_API_KEY']
    private={'DEEPSEEK_API_KEY':key,'OPENAI_API_KEY':key}
    if github_token:private['AUTOKAGGLE_LITE_GITHUB_TOKEN']=github_token
    kube.run('patch','secret',service+'-secrets','-n',namespace,'--type=merge','--patch-file=/dev/stdin',document={'stringData':private})
    settings={'OPENAI_BASE_URL':'https://api.deepseek.com','AUTOKAGGLE_MODEL':'deepseek-v4-pro',
              'AUTOKAGGLE_LITE_PROVIDER':'deepseek','AUTOKAGGLE_LITE_DEEPSEEK_MODEL':'deepseek-v4-pro'}
    if github_owner:settings['AUTOKAGGLE_LITE_GITHUB_OWNER']=github_owner
    changes={'volumes':[{'name':'source','configMap':{'name':name}}]}
    if build_image:
        if service!='lite' or '@sha256:' not in build_image:raise ValueError('Only Lite accepts an immutable build image.')
        api=kube.json('get','endpoints','kubernetes','-n','default')['subsets'][0]['addresses'][0]['ip']
        dns=kube.json('get','service','kube-dns','-n','kube-system')['spec']['clusterIP']
        for resource in lite_jobs.resources(api,[dns]):kube.run('apply','-f','-',document=resource)
        settings.update(AUTOKAGGLE_LITE_BUILD_RUNTIME='kubernetes',AUTOKAGGLE_LITE_BUILD_IMAGE=build_image,
                        AUTOKAGGLE_LITE_BUILD_CLAIM='lite-data',AUTOKAGGLE_LITE_BUILD_DATA='/data',AUTOKAGGLE_LITE_GATEWAY_BIND='0.0.0.0')
        changes.update(serviceAccountName='lite-builder-control',automountServiceAccountToken=True,
            containers=[{'name':pod['containers'][0]['name'],'image':build_image,'imagePullPolicy':'Never',
                         'env':[{'name':'AUTOKAGGLE_LITE_POD_IP','valueFrom':{'fieldRef':{'fieldPath':'status.podIP'}}}]}])
    kube.run('patch','configmap',service+'-config','-n',namespace,'--type=merge','--patch-file=/dev/stdin',document={'data':settings})
    patch={'spec':{'template':{'metadata':{'annotations':{'autokaggle/source-sha256':digest,
        'autokaggle/model-sha256':hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()}},'spec':changes}}}
    kube.run('patch','deployment',service,'-n',namespace,'--type=strategic','--patch-file=/dev/stdin',document=patch)
    kube.run('rollout','status','deployment/'+service,'-n',namespace,'--timeout=300s',timeout=330)
    return {'service':service,'source_sha256':digest,'before':evidence}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('service',choices=['web','lite']);p.add_argument('--model-env',type=Path,required=True)
    p.add_argument('--build-image');p.add_argument('--github-owner');p.add_argument('--github-env',type=Path)
    a=p.parse_args();model=dotenv_values(a.model_env)
    if not model.get('DEEPSEEK_API_KEY'):raise ValueError('The private model file has no DeepSeek key.')
    token=(dotenv_values(a.github_env).get('AUTOKAGGLE_LITE_GITHUB_TOKEN') if a.github_env else None)
    source,digest=web.bundle()
    with private_kubeconfig() as config:
        print(json.dumps(update(Kubectl(config),a.service,source,digest,model,build_image=a.build_image,github_owner=a.github_owner,github_token=token)))

if __name__=='__main__':main()
