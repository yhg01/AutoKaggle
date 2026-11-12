"""Lite admin records are accurate, bounded, private, and safe to read."""
import copy
import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from autokaggle import lite_diagnostics as diag, observability as obs
from autokaggle.store import Store, public_project
from autokaggle.tests.test_observability import app
from autokaggle.tests.test_access import sign_in


def seeded(store):
    p = store.create('researcher', 'Lite logs')
    p['lite'] = {'status': 'idle', 'model_calls': 8, 'round': 2, 'job_id': 'job',
                 'messages': [{'id': 'm1', 'role': 'user', 'content': 'Optimize the objective.'}],
                 'contract': {'objective': 'Minimize cost'}, 'sources': [], 'history': [], 'results': []}
    store.save(p)
    state = copy.deepcopy(p['lite'])
    state['_repository_directory'] = str(store.directory(p['id']))
    diag.bind(store)
    return p, state


def read(store, identifier):
    with store.connection() as con:
        return json.loads(con.execute('SELECT body FROM projects WHERE id=?', (identifier,)).fetchone()[0])


def test_request_capture_persists_exact_request_and_usage_without_secrets(tmp_path):
    store = Store(tmp_path)
    p, state = seeded(store)
    def create(**kwargs):
        assert read(store, p['id'])['_model_traces'][-1]['status'] == 'running'
        return NS(model='test-provider-model', choices=[NS(finish_reason='stop', message=NS(content='{"ok":true}'))],
                  usage=NS(prompt_tokens=22, completion_tokens=12, completion_tokens_details=NS(reasoning_tokens=5)))
    client = NS(chat=NS(completions=NS(create=create)))
    kwargs = {'model': 'test', 'messages': [{'role': 'system', 'content': 'System instruction'},
              {'role': 'assistant', 'content': 'visible', 'reasoning_content': 'not-a-public-explanation'}], 'apiKey': 'ephemeral-key'}
    diag.request(state, client, **kwargs)
    saved = read(store, p['id']); trace = saved['_model_traces'][0]
    assert trace['status'] == 'completed' and trace['usage']['input_tokens'] == 22
    assert trace['trigger'] == {'message_id': 'm1', 'interview_round': 2}
    assert saved['_lite_model_requests'] == 1 and saved['_lite_untraced_turns'] == 7
    assert saved['lite']['model_calls'] == 8  # Requests and interview turns are different counts.
    assert json.loads(trace['input'])['messages'][0]['content'] == 'System instruction'
    assert 'ephemeral-key' not in json.dumps(trace) and 'not-a-public-explanation' not in json.dumps(trace)
    assert '_model_traces' not in public_project(saved)
    assert kwargs['apiKey'] == 'ephemeral-key'  # Redaction never changes the actual request.


def test_failures_and_tool_calls_are_separate_records(tmp_path):
    store = Store(tmp_path); p, state = seeded(store)
    def fail(**kwargs):
        raise ValueError('must-not-save-this-secret')
    with pytest.raises(ValueError):
        diag.request(state, NS(chat=NS(completions=NS(create=fail))), model='test')
    response = NS(model='test', choices=[NS(finish_reason='tool_calls', message=NS(content=None,
        tool_calls=[NS(model_dump=lambda **kw: {'id': 'tool1', 'function': {'name': 'read_repository', 'arguments': '{}'}})]))])
    diag.request(state, NS(chat=NS(completions=NS(create=lambda **kw: response))), model='test')
    saved = read(store, p['id']); traces = saved['_model_traces']
    assert [t['status'] for t in traces] == ['failed', 'completed']
    assert saved['_lite_model_requests'] == 2 and json.loads(traces[1]['tool_calls'])[0]['id'] == 'tool1'
    assert 'must-not-save-this-secret' not in json.dumps(saved)


def test_retention_stale_jobs_erasure_and_restart(tmp_path):
    store = Store(tmp_path); p, state = seeded(store)
    for i in range(35):
        diag.save(state, {'id': str(i), 'status': 'completed'})
    saved = read(store, p['id'])
    assert len(saved['_model_traces']) == 30 and saved['_lite_model_requests'] == 35
    diag.save({**state, 'job_id': 'old'}, {'id': 'stale', 'status': 'running'})
    assert read(store, p['id']) == saved
    diag.save(state, {'id': 'inflight', 'status': 'running'})
    restarted = Store(tmp_path)
    assert read(restarted, p['id'])['_model_traces'][-1]['status'] == 'interrupted'
    with store.connection() as con:
        con.execute('DELETE FROM projects WHERE id=?', (p['id'],))
    diag.save(state, {'id': 'deleted', 'status': 'completed'})
    with store.connection() as con:
        assert con.execute('SELECT count(*) FROM projects').fetchone()[0] == 0


def test_admin_lite_snapshot_and_build_log(app, tmp_path):
    store = app.state.store; p, state = seeded(store)
    build = 'a' * 16
    p['lite_evaluator'] = {'builds': [{'id': build, 'status': 'ready'}]}
    store.save(p)
    directory = store.directory(p['id']) / 'lite-evaluator' / 'jobs' / build
    directory.mkdir(parents=True)
    log = directory / 'agent.log'
    log.write_text('agent output\napiKey: gateway-private-key\ngithub_pat_private123\nsk-providerkey\na@lab.org')
    base = f'/api/internal/projects/{p["id"]}'
    url = f'{base}/lite-builds/{build}/logs/agent'
    before = read(store, p['id'])
    with TestClient(app, base_url='https://testserver') as client:
        assert client.get(url).status_code == 403
        sign_in(client)
        listing = client.get('/api/internal/projects').json()['projects'][0]
        assert listing['mode'] == 'lite' and listing['interview_turns'] == 8
        assert listing['model_calls'] is None and listing['status'] == 'idle'
        detail = client.get(base).json()['project']
        assert detail['lite']['messages'][0]['id'] == 'm1'
        assert detail['lite_evaluator']['builds'][0]['id'] == build
        response = client.get(url)
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        assert 'agent output' in response.text
        for private in ('gateway-private-key', 'github_pat_private123', 'sk-providerkey', 'a@lab.org'):
            assert private not in response.text
        assert client.get(url.replace('/agent', '/test')).status_code == 404
        assert client.get(url.replace(build, 'b' * 16)).status_code == 404
        assert client.get(url.replace('/agent', '/config')).status_code == 404
        log.write_text('x' * (obs.LOG_LIMIT + 100) + '\nlast line')
        data = client.get(url).json()
        assert data['truncated'] and len(data['text']) == obs.LOG_LIMIT and data['text'].endswith('last line')
        log.unlink(); log.symlink_to(tmp_path / 'outside')
        assert client.get(url).status_code == 404
        log.unlink(); directory.rename(directory.with_name('original'))
        directory.symlink_to(directory.with_name('original'), target_is_directory=True)
        assert client.get(url).status_code == 404
    assert read(store, p['id']) == before


def test_validation_updates_only_its_request_record(tmp_path):
    store=Store(tmp_path);p,state=seeded(store)
    trace={'id':'last','status':'completed'}
    diag.save(state,trace)
    assert diag.parse(NS(parse_proposal=lambda *args: {'ok':True}),state,None,trace)=={'ok':True}
    assert read(store,p['id'])['_model_traces'][-1]['validation']['status']=='accepted'
    def bad(*args):raise ValueError('bad schema')
    with pytest.raises(ValueError):diag.parse(NS(parse_proposal=bad),state,None,trace)
    saved=read(store,p['id'])
    assert saved['_model_traces'][-1]['validation']['status']=='rejected'
    assert saved['_lite_model_requests']==1
