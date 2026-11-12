from pathlib import Path
import pytest
from autokaggle.lite_kubernetes import KubernetesRuntime
from autokaggle.deploy import lite_jobs


def runtime(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOKAGGLE_LITE_BUILD_DATA',str(tmp_path))
    monkeypatch.setenv('AUTOKAGGLE_LITE_BUILD_IMAGE','local/test@sha256:'+'a'*64)
    return KubernetesRuntime()


def test_jobs_cannot_read_credentials_or_other_projects(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch);p=tmp_path/'projects'/('a'*36)/'lite-evaluator'/'jobs'/('a'*16)
    for name in ['work','home']:(p/name).mkdir(parents=True)
    manifest=r.manifest('test',['{python}','task.py'],{'work':(p/'work','rw'),'home':(p/'home','rw')},'{work}',{},60)
    spec=manifest['spec']['template']['spec'];c=spec['containers'][0]
    assert 'runtimeClassName' not in spec and spec['automountServiceAccountToken'] is False
    assert c['securityContext']['readOnlyRootFilesystem'] and c['securityContext']['capabilities']['drop']==['ALL']
    assert c['resources']['limits']['cpu']=='2' and manifest['spec']['backoffLimit']==0
    assert not any('secret' in v or 'hostPath' in v for v in spec['volumes'])
    assert all(m.get('subPath','').startswith('projects/'+('a'*36)+'/lite-evaluator/jobs/') for m in c['volumeMounts'] if m['name']=='work')
    with pytest.raises(ValueError):r.manifest('bad',['true'],{'work':(tmp_path/'projects','rw')},'{work}',{},60)
    with pytest.raises(ValueError):r.manifest('bad',['true'],{'work':(p/'work','rw'),'home':(p.parent/('b'*16)/'home','rw')},'{work}',{},60)


def test_policy_blocks_private_network_and_application_port():
    items=lite_jobs.resources('10.0.0.1')
    policy=next(i for i in items if i['metadata']['name']=='lite-build-boundary')['spec']
    assert policy['ingress']==[]
    assert '10.0.0.0/8' in policy['egress'][-1]['to'][0]['ipBlock']['except']
    assert policy['egress'][1]['ports']==[{'port':32768,'endPort':60999,'protocol':'TCP'}]
    role=next(i for i in items if i['kind']=='Role')
    assert all('secrets' not in r['resources'] and 'pods/exec' not in r['resources'] for r in role['rules'])


def test_job_logs_are_available_before_completion_and_redacted(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch)
    monkeypatch.setattr(r,'manifest',lambda *args: {})
    monkeypatch.setattr('autokaggle.lite_kubernetes.time.sleep',lambda *args: None)
    log=tmp_path/'agent.log'; polls=[]; actions=[]
    def request(method,path,body=None,text=False):
        actions.append((method,path))
        if '/log?' in path:return 'build progress apiKey: ephemeral-secret'
        if '/pods?' in path:return {'items':[{'metadata':{'name':'worker'}}]}
        if method=='GET':
            polls.append(path)
            if len(polls)>1:
                assert 'build progress' in log.read_text()
                assert 'ephemeral-secret' not in log.read_text()
                return {'status':{'succeeded':1,'conditions':[{'status':'True','type':'Complete'}]}}
        return {}
    monkeypatch.setattr(r,'request',request)
    code,_=r.run([],{},'',{},60,log,'agent')
    assert code==0 and actions[-1][0]=='DELETE'
    assert len([p for m,p in actions if '/log?' in p])==2


def test_missing_pod_logs_preserve_previous_snapshot(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch);log=tmp_path/'agent.log';log.write_text('saved output')
    def request(*args,**kwargs):raise RuntimeError('pending pod')
    monkeypatch.setattr(r,'request',request)
    assert not r.capture_logs('job',log)
    assert log.read_text()=='saved output'
