import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from autokaggle.app import create_app
from autokaggle.tests.test_documents import READABLE, docx, pdf


@pytest.fixture
def session(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOKAGGLE_PRIVATE_MODE','0')
    app=create_app(tmp_path)
    with TestClient(app) as client:
        response=client.post('/api/lite/projects',json={'title':'Attachments','organizer_email':'test@example.org','storage_accepted':True})
        assert response.status_code==200
        yield client, '/api/projects/'+response.json()['id']+'/lite'
    app.state.pool.shutdown(wait=True)


@pytest.mark.parametrize('name,body', [('notes.txt',b'Data is measured in seconds.'),('rows.csv',b'id,value\n1,2\n'),('scorer.py',b'raise RuntimeError("must never execute")'),('notes.docx',docx()),('paper.pdf',pdf())])
def test_file_is_context_not_executed(session,name,body):
    c,p=session
    result=c.post(p+'/attachments',files={'file':(name,body,'application/octet-stream')})
    assert result.status_code==200, result.text
    data=result.json()
    assert data['sources'][0]['kind']=='attachment'
    assert not data['contract']
    again=c.post(p+'/attachments',files={'file':(name,body,'application/octet-stream')})
    assert again.status_code==200
    assert len(again.json()['sources'])==1


def test_empty_and_binary_rejected(session):
    c,p=session
    assert c.post(p+'/attachments',files={'file':('empty.txt',b'')}).status_code==422
    assert c.post(p+'/attachments',files={'file':('binary.bin',bytes(range(256))*10)}).status_code==422
    assert not c.get(p).json()['sources']


def test_attachment_other_session_denied(session):
    c,p=session
    stranger=TestClient(c.app)
    assert stranger.post(p+'/attachments',files={'file':('x.txt',b'private source')}).status_code in (401,404)
