"""Internal evaluator builds in bounded restricted container jobs on the existing Civo node.

Only the trusted web process has Kubernetes credentials. Each job receives its
own workspace and a short-lived model token. It cannot mount the project store.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import secrets
import time
import httpx


class KubernetesRuntime:
    kind = 'kubernetes'

    def __init__(self):
        self.namespace = os.getenv('AUTOKAGGLE_LITE_BUILD_NAMESPACE', 'autokaggle-web')
        self.image = os.getenv('AUTOKAGGLE_LITE_BUILD_IMAGE', '')
        self.claim = os.getenv('AUTOKAGGLE_LITE_BUILD_CLAIM', 'lite-data')
        self.root = Path(os.getenv('AUTOKAGGLE_LITE_BUILD_DATA', '/data')).resolve()
        self.auth = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.url = 'https://' + os.getenv('KUBERNETES_SERVICE_HOST', 'kubernetes.default.svc') + ':' + os.getenv('KUBERNETES_SERVICE_PORT', '443')

    def request(self, method, path, body=None, text=False):
        with httpx.Client(verify=str(self.auth/'ca.crt'), timeout=30, trust_env=False) as client:
            response=client.request(method, self.url+path, json=body,
                headers={'Authorization':'Bearer '+(self.auth/'token').read_text().strip()})
        if response.status_code == 404 and method == 'DELETE':
            return {}
        if response.status_code >= 400:
            raise RuntimeError('The evaluator job service rejected the operation ('+str(response.status_code)+').')
        return response.text if text else response.json()

    def available(self):
        if not self.image or '@sha256:' not in self.image or not (self.auth/'token').is_file():
            return False, 'The isolated Civo build service is not configured.'
        return True, ''

    def prepare(self):
        ok,reason=self.available()
        if not ok: raise RuntimeError(reason)

    def gateway_host(self):
        host=os.getenv('AUTOKAGGLE_LITE_POD_IP','')
        if not host: raise RuntimeError('The build gateway address is not configured.')
        return host

    def describe(self):
        return {'kind':self.kind,'image':self.image,'cpus':2,'memory_gb':4,
                'isolation':'Restricted container, non-root, no service credentials, workspace-only mounts; public HTTPS and a one-job model gateway.'}

    def manifest(self, name, argv, mounts, cwd, env, timeout):
        from .lite_build import _substitute
        mapping={key:'/mnt/'+key for key in mounts};mapping.update(python='python',opencode='opencode')
        mounted=[];job_root=None
        for key,(directory,mode) in mounts.items():
            relative=Path(directory).resolve().relative_to(self.root)
            # One job cannot request the parent project directory or another job's files.
            parts=relative.parts
            if len(parts)!=6 or parts[0]!='projects' or not re.fullmatch('[a-f0-9-]{36}',parts[1]) or parts[-4]!='lite-evaluator' or parts[-3]!='jobs' or not re.fullmatch('[a-f0-9]{16}',parts[-2]) or parts[-1] not in {'work','home','in','out'}:
                raise ValueError('Build mounts must be inside one evaluator job directory.')
            parent=parts[:-1]
            if job_root is not None and parent!=job_root: raise ValueError('Build mounts cross job boundaries.')
            job_root=parent
            mounted.append({'name':'work','mountPath':'/mnt/'+key,'subPath':str(relative),'readOnly':mode=='ro'})
        environment={'HOME':'/mnt/home','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1','PIP_NO_INPUT':'1',
                     **{k:_substitute([v],mapping)[0] for k,v in env.items()}}
        return {'apiVersion':'batch/v1','kind':'Job','metadata':{'name':name,'namespace':self.namespace,'labels':{'app':'autokaggle-lite-build'}},
            'spec':{'backoffLimit':0,'activeDeadlineSeconds':int(timeout),'ttlSecondsAfterFinished':600,'template':{
                'metadata':{'labels':{'app':'autokaggle-lite-build'}},'spec':{
                    'automountServiceAccountToken':False,'enableServiceLinks':False,'restartPolicy':'Never',
                    'securityContext':{'runAsNonRoot':True,'runAsUser':1000,'runAsGroup':1000,'fsGroup':1000,'fsGroupChangePolicy':'OnRootMismatch','seccompProfile':{'type':'RuntimeDefault'}},
                    'containers':[{'name':'worker','image':self.image,'imagePullPolicy':'Never','workingDir':_substitute([cwd],mapping)[0],
                        'command':_substitute(argv,mapping),'env':[{'name':k,'value':str(v)} for k,v in environment.items()],
                        'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
                        'resources':{'requests':{'cpu':'500m','memory':'512Mi'},'limits':{'cpu':'2','memory':'4Gi','ephemeral-storage':'2Gi'}},
                        'volumeMounts':mounted+[{'name':'tmp','mountPath':'/tmp'}]}],
                    'volumes':[{'name':'work','persistentVolumeClaim':{'claimName':self.claim}},{'name':'tmp','emptyDir':{'sizeLimit':'2Gi'}}]}}}}

    def capture_logs(self, name, log):
        """Save a bounded snapshot during a job. A pending pod may have no log yet."""
        from .observability import scrub
        try:
            pods = self.request('GET', '/api/v1/namespaces/'+self.namespace+'/pods?labelSelector=job-name%3D'+name)
            chunks = []
            for pod in pods.get('items', []):
                chunks.append(self.request('GET', '/api/v1/namespaces/'+self.namespace+'/pods/'+pod['metadata']['name']+'/log?tailLines=2000&limitBytes=2000000', text=True))
            if chunks:
                target = Path(log)
                temporary = target.with_suffix('.log.tmp')
                temporary.write_text(scrub('\n'.join(chunks)[-2000000:]))
                os.replace(temporary, target)
        except (RuntimeError, OSError, httpx.HTTPError):
            # Log availability must not stop a valid evaluator run or erase its last snapshot.
            return False
        return True

    def run(self, argv, mounts, cwd, env, timeout, log, label):
        name='lite-build-'+label+'-'+secrets.token_hex(5)
        path='/apis/batch/v1/namespaces/'+self.namespace+'/jobs'
        started=time.monotonic();code=None;last_log=started-10
        self.request('POST',path,self.manifest(name,argv,mounts,cwd,env,timeout))
        try:
            while time.monotonic()-started < timeout+30:
                job=self.request('GET',path+'/'+name)
                if time.monotonic()-last_log >= 10:
                    self.capture_logs(name, log)
                    last_log=time.monotonic()
                if any(c.get('status')=='True' and c.get('type') in {'Complete','Failed'} for c in job.get('status',{}).get('conditions',[])):
                    code=0 if job.get('status',{}).get('succeeded') else 1
                    break
                time.sleep(3)
        finally:
            self.capture_logs(name, log)
            self.request('DELETE',path+'/'+name,{'propagationPolicy':'Background'})
        return code,round(time.monotonic()-started,1)
