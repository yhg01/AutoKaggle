"""Temporary verified-email access. Mail transport is replaced, not claimed live."""
import pytest
from fastapi.testclient import TestClient
from autokaggle import notifications
from autokaggle.app import create_app
from autokaggle.tests.test_access import TEST_CODE, challenge
from autokaggle.deploy import lite_web, rollout


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOKAGGLE_PRIVATE_MODE', '1')
    monkeypatch.setenv('AUTOKAGGLE_ADMIN_ACCESS_CODE', TEST_CODE)
    monkeypatch.setenv('AUTOKAGGLE_PUBLIC_BASE_URL', 'https://testserver')
    monkeypatch.setenv('AUTOKAGGLE_LITE_ACCESS_POLICY', 'verified_email')
    monkeypatch.setenv('AUTOKAGGLE_LITE_MEMBERS', '')
    monkeypatch.setenv('AUTOKAGGLE_MODE', 'rules')
    sent = []
    monkeypatch.setattr(notifications, 'email_login_available', lambda: True)
    monkeypatch.setattr(notifications, 'send_login_code', lambda email, code: sent.append((email, code)))
    app = create_app(tmp_path)
    yield app, sent
    app.state.pool.shutdown(wait=True)


def login(client, sent, email):
    response = client.post('/api/access/email/request', json={'email': email}, headers=challenge(client))
    assert response.status_code == 200
    response = client.post('/api/access/email/verify', json={'challenge_id': response.json()['challenge_id'], 'code': sent[-1][1]}, headers=challenge(client))
    assert response.status_code == 200
    assert response.json()['is_admin'] is False


def test_verified_nonmember_can_create_resume_and_share_but_not_read_other_projects(service, monkeypatch):
    app, sent = service
    with TestClient(app, base_url='https://testserver') as owner, TestClient(app, base_url='https://testserver') as other:
        login(owner, sent, 'first@example.org')
        assert owner.get('/lite').status_code == 200
        p = owner.post('/api/lite/projects', json={'organizer_email': 'first@example.org', 'storage_accepted': True})
        assert p.status_code == 200, p.text
        root = '/api/projects/' + p.json()['id']
        assert owner.get(root + '/lite').status_code == 200
        assert owner.get('/api/internal/projects').status_code in (401,403)
        login(other, sent, 'second@example.org')
        assert other.get(root + '/lite').status_code == 404
        assert other.get('/api/lite/projects').json()['projects'] == []
        code = owner.post(root + '/handoff').json()['code']
        assert other.post('/api/handoffs/redeem', json={'code': code, 'accepted': True}).status_code == 200
        assert other.get(root + '/lite').status_code == 200
        monkeypatch.setenv('AUTOKAGGLE_LITE_ACCESS_POLICY', 'members')
        assert owner.get(root + '/lite').status_code == 403
        monkeypatch.setenv('AUTOKAGGLE_LITE_ACCESS_POLICY', 'verified_email')
        assert owner.get(root + '/lite').status_code == 200


def test_anonymous_and_forged_email_cannot_enter(service):
    app, _ = service
    with TestClient(app, base_url='https://testserver') as client:
        assert client.get('/lite', follow_redirects=False).status_code == 303
        assert client.get('/api/lite/projects').status_code == 401
        client.cookies.set('autokaggle_session', 'first@example.org')
        assert client.post('/api/lite/projects', json={'organizer_email': 'first@example.org', 'storage_accepted': True}).status_code in (401,403)


def test_unknown_policy_fails_closed(service, monkeypatch):
    app, sent = service
    with TestClient(app, base_url='https://testserver') as client:
        login(client, sent, 'third@example.org')
        monkeypatch.setenv('AUTOKAGGLE_LITE_ACCESS_POLICY', 'typo')
        assert client.get('/api/lite/projects').status_code == 503


def test_deployer_retains_private_mode_and_rejects_full_policy_change():
    items = lite_web.resources(b'source', 'a'*64, {'OPENAI_API_KEY': 'test'}, [], access_policy='verified_email')
    config = next(x['data'] for x in items if x['metadata']['name'] == 'lite-config')
    assert config['AUTOKAGGLE_PRIVATE_MODE'] == '1'
    assert config['AUTOKAGGLE_LITE_ACCESS_POLICY'] == 'verified_email'
    with pytest.raises(ValueError):
        rollout.update(None, 'web', b'', '', {}, lite_access_policy='verified_email')
    with pytest.raises(ValueError):
        lite_web.resources(b'source', 'a'*64, {}, [], access_policy='typo')
