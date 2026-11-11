"""Public-answer research without weakening the private-answer path."""
import base64
import io
import json
import stat
import zipfile

from fastapi.testclient import TestClient
import pytest

from autokaggle import research_review
from autokaggle.tests.test_workflow import case, build


def code_zip(version, source='print("example")\n', **overrides):
    manifest = {'format': research_review.FORMAT, 'entrypoint': 'solution.py', 'command': 'python solution.py',
                'environment': 'Python 3.12 standard library', 'seeds': 'None', 'data_version': version,
                'model_assets': 'None', 'resources': 'One CPU', 'prior_answer_access': 'No earlier access'}
    manifest.update(overrides)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('solution.py', source)
        z.writestr('reproduction.json', json.dumps(manifest))
    return base64.b64encode(stream.getvalue()).decode()


def public_case(case):
    app, client, root, pid = case
    client.patch(root, json={'answers': {'labels_public': 'yes', 'research_mode': 'public_research'}}).raise_for_status()
    result = build(case)
    assert result['status'] == 'ready_for_review', result
    predictions = (app.state.store.directory(pid) / 'workflow/private/baseline_predictions.csv').read_text()
    return result, {'request_id': 'public-attempt-1', 'predictions_csv': predictions, 'code_zip_base64': code_zip(result['version'])}


def clear(*args):
    return {'status': 'clear', 'summary': 'No concrete concern.', 'findings': [], 'model': 'unit-test'}


def test_public_package_disclosure_and_no_answer_files(case):
    result, body = public_case(case)
    app, client, root, pid = case
    z = zipfile.ZipFile(io.BytesIO(client.get(root + '/workflow/package').content))
    assert {'train.csv', 'validation_features.csv', 'reproduction.json'} <= set(z.namelist())
    for name in ('README.md', 'AGENTS.md', 'index.html'):
        assert 'not a blind evaluation' in z.read(name).decode()
    assert not any('truth' in name for name in z.namelist())
    spec = json.loads(z.read('challenge.json'))
    assert spec['access']['test_answers'] != 'private'
    assert spec['research_mode'] == 'public_research'
    assert 'reproduction-code' in client.get(root + '/workflow/preview').text


@pytest.mark.parametrize('change', [{'labels_public': 'unknown'}, {'labels_public': 'no'}, {'rights': 'unknown'}, {'data_origin': 'unknown'}])
def test_public_mode_keeps_other_gates(case, change):
    app, client, root, pid = case
    public_case(case)
    client.patch(root, json={'answers': change}).raise_for_status()
    assert build(case)['status'] == 'needs_changes'


def test_private_public_labels_still_block(case):
    app, client, root, pid = case
    client.patch(root, json={'answers': {'data_origin': 'public', 'labels_public': 'yes'}}).raise_for_status()
    assert build(case)['status'] == 'needs_changes'
    client.patch(root, json={'answers': {'labels_public': 'no'}}).raise_for_status()
    assert build(case)['status'] == 'ready_for_review'
    predictions = (app.state.store.directory(pid) / 'workflow/private/baseline_predictions.csv').read_text()
    response = client.post(root + '/workflow/submissions', json={'request_id': 'private-normal', 'predictions_csv': predictions})
    assert response.json()['status'] == 'scored'
    assert 'review' not in response.json()
    assert 'reproduction-code' not in client.get(root + '/workflow/preview').text


def test_requires_code_on_both_endpoints_and_keeps_quota(case, monkeypatch):
    result, body = public_case(case)
    app, client, root, pid = case
    missing = {k: v for k, v in body.items() if k != 'code_zip_base64'}
    assert client.post(root + '/workflow/submissions', json=missing).status_code == 422
    access = client.post(root + '/workflow/access').json()
    headers = {'Authorization': 'Bearer ' + access['token']}
    assert client.post(access['submission_url'], headers=headers, json=missing).status_code == 422
    monkeypatch.setattr(research_review, 'review', clear)
    response = client.post(access['submission_url'], headers=headers, json=body)
    response.raise_for_status()
    saved = response.json()
    assert saved['status'] == 'scored' and saved['remaining_today'] == 4
    assert saved['reproduction']['status'] == 'not_run'
    assert client.post(access['submission_url'], headers=headers, json=body).json() == saved
    changed = {**body, 'code_zip_base64': code_zip(result['version'], 'print("changed")')}
    assert client.post(access['submission_url'], headers=headers, json=changed).status_code == 422
    artifact = saved['artifact_id']
    assert client.get(root + f'/attempts/{artifact}/code.zip').content == base64.b64decode(body['code_zip_base64'])
    with TestClient(app) as stranger:
        assert stranger.get(root + f'/attempts/{artifact}/code.zip').status_code == 404
        assert stranger.get(root + f'/attempts/{artifact}/code.zip', headers=headers).status_code == 404
    assert client.get(root + f'/attempts/{artifact}/../../dataset.csv').status_code == 404


def test_flagged_review_withholds_score(case, monkeypatch):
    result, body = public_case(case)
    app, client, root, pid = case
    monkeypatch.setattr(research_review, 'review', lambda *a: {'status': 'flagged', 'summary': 'Embedded answers.', 'findings': [{'file':'solution.py', 'evidence':'print', 'reason':'fixture'}]})
    response = client.post(root + '/workflow/submissions', json=body).json()
    assert response['status'] == 'review_flagged' and 'score' not in response
    assert response['remaining_today'] == 4
    assert client.post(root + f"/attempts/{response['artifact_id']}/review").status_code == 422


def test_unavailable_review_retry_does_not_use_quota(case, monkeypatch):
    result, body = public_case(case)
    app, client, root, pid = case
    # Rules mode cannot impersonate a live model review.
    saved = client.post(root + '/workflow/submissions', json=body).json()
    assert saved['status'] == 'review_pending' and 'score' not in saved
    monkeypatch.setattr(research_review, 'review', clear)
    retried = client.post(root + f"/attempts/{saved['artifact_id']}/review").json()
    assert retried['status'] == 'scored' and retried['remaining_today'] == 4
    assert client.post(root + '/workflow/submissions', json=body).json() == retried


def test_version_change_revokes_retry_and_token(case):
    result, body = public_case(case)
    app, client, root, pid = case
    access = client.post(root + '/workflow/access').json()
    saved = client.post(root + '/workflow/submissions', json=body).json()
    client.patch(root, json={'answers': {'research_mode': 'private'}}).raise_for_status()
    assert client.post(root + f"/attempts/{saved['artifact_id']}/review").status_code == 422
    assert client.post(access['submission_url'], headers={'Authorization': 'Bearer ' + access['token']}, json=body).status_code == 401


@pytest.mark.parametrize('name', ['../bad.py', '/bad.py', 'a/../bad.py', 'a//bad.py', 'evil.exe', 'bad\\file.py'])
def test_unsafe_zip_names_rejected(name):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr(name, 'print(1)')
    with pytest.raises(ValueError):
        research_review.unpack(base64.b64encode(stream.getvalue()).decode(), 'v1')


def test_zip_links_and_large_expansion_rejected():
    for large in (False, True):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            info = zipfile.ZipInfo('source.py')
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            if large:
                z.writestr('source.py', 'a' * (research_review.MAX_TEXT + 1))
            else:
                z.writestr(info, '/etc/passwd')
        with pytest.raises(ValueError):
            research_review.unpack(base64.b64encode(stream.getvalue()).decode(), 'v1')


def test_manifest_version_and_placeholders_rejected():
    for encoded in (code_zip('old'), code_zip('v1', prior_answer_access='REPLACE disclosure')):
        with pytest.raises(ValueError): research_review.unpack(encoded, 'v1')


def test_review_retries_bounded_and_artifacts_checked(case):
    _, body = public_case(case)
    app, client, root, pid = case
    saved = client.post(root + '/workflow/submissions', json=body).json()
    endpoint = root + f"/attempts/{saved['artifact_id']}/review"
    assert client.post(endpoint).json()['review_attempts'] == 2
    assert client.post(endpoint).json()['review_attempts'] == 3
    assert client.post(endpoint).status_code == 422
    with app.state.store.connection() as con:
        assert con.execute('SELECT COUNT(*) FROM draft_submissions').fetchone()[0] == 1


def test_invalid_predictions_skip_paid_review(case, monkeypatch):
    _, body = public_case(case)
    app, client, root, pid = case
    def unexpected(*a): raise AssertionError('Review should not run')
    monkeypatch.setattr(research_review, 'review', unexpected)
    result = client.post(root + '/workflow/submissions', json={**body, 'predictions_csv':'wrong,columns\n1,2'}).json()
    assert result['status'] == 'invalid' and result['remaining_today'] == 4


def test_code_review_never_receives_labels_or_predictions(case, monkeypatch):
    _, body = public_case(case)
    app, client, root, pid = case
    def inspect(files, contract):
        assert set(contract) == {'version', 'target', 'metric', 'output_columns'}
        assert set(files) == {'solution.py', 'reproduction.json'}
        assert body['predictions_csv'] not in json.dumps([files, contract])
        return clear()
    monkeypatch.setattr(research_review, 'review', inspect)
    assert client.post(root + '/workflow/submissions', json=body).json()['status'] == 'scored'


@pytest.mark.parametrize('response', [
    {'status':'clear','summary':'OK','findings':[{'file':'solution.py','evidence':'x','reason':'x'}]},
    {'status':'flagged','summary':'Bad','findings':[{'file':'missing.py','evidence':'x','reason':'x'}]},
    {'status':'flagged','summary':'Bad','findings':[{'file':'solution.py','evidence':'invented evidence','reason':'x'}]},
    {'status':'clear','summary':'','findings':[]},
    {'status':'approved','summary':'OK','findings':[]},
])
def test_invalid_model_reports_fail_closed(monkeypatch, response):
    from types import SimpleNamespace
    import openai
    from autokaggle import advisor
    class Client:
        def __init__(self, **kwargs): self.responses = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kwargs):
            assert 'tools' not in kwargs
            return SimpleNamespace(status='completed', output_text=json.dumps(response), model='test', usage=None)
    monkeypatch.setattr(advisor, 'configured', lambda: True)
    monkeypatch.setattr(openai, 'OpenAI', Client)
    assert research_review.review({'solution.py':'print(1)'}, {})['status'] == 'unavailable'
