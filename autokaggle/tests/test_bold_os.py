import json
import httpx
import pytest
from autokaggle import bold_os


def test_only_declared_read_tools_and_discovered_ids_are_callable():
    calls=[]
    def send(req):
        calls.append(req)
        assert req.method=='GET' and str(req.url).startswith(bold_os.BASE)
        assert req.headers['Authorization']=='Bearer private-test-token'
        if req.url.path.endswith('list_projects'):
            return httpx.Response(200,json={'total':1,'projects':[{'id':'p1','title':'World models','url':'https://bold-lab-ai.github.io/bold-os/project.html#id=p1','email':'private@example.org'}]})
        return httpx.Response(200,json={'id':'p1','title':'World models','slack_channel':'private','abstract':'Compare models'})
    client=bold_os.Client('private-test-token',transport=httpx.MockTransport(send))
    assert 'error' in client.call('projects',{'action':'register'})
    assert 'error' in client.call('bold_get_project',{'id':'p1'})
    result=client.call('bold_list_projects',{'query':'world'})
    assert 'email' not in result['untrusted_content']
    result=client.call('bold_get_project',{'id':'p1'})
    assert 'Compare models' in result['untrusted_content'] and 'slack_channel' not in result['untrusted_content']
    assert len(calls)==2


@pytest.mark.parametrize('status',[301,302,401,403,404,429,500])
def test_errors_do_not_echo_headers_body_or_follow_redirects(status):
    calls=[]
    def send(req):
        calls.append(req)
        return httpx.Response(status,headers={'location':'https://untrusted.example'},text='private-test-token')
    result=bold_os.Client('private-test-token',transport=httpx.MockTransport(send)).call('bold_list_tools',{})
    assert result['status']==status and 'private-test-token' not in json.dumps(result)
    assert len(calls)==1


@pytest.mark.parametrize('body',[b'x'*256001,b'not json',b'[]',b'{"secret":"private-test-token"}'])
def test_invalid_or_secret_response_is_blocked(body):
    client=bold_os.Client('private-test-token',transport=httpx.MockTransport(lambda req:httpx.Response(200,content=body)))
    result=client.call('bold_list_tools',{})
    assert 'error' in result and 'private-test-token' not in json.dumps(result)


def test_budget_and_arguments():
    client=bold_os.Client('token',transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'built_in':[]})))
    assert 'error' in client.call('bold_list_tools',{'url':'https://evil.example'})
    for _ in range(6):assert 'error' not in client.call('bold_list_tools',{})
    assert 'error' in client.call('bold_list_tools',{})
    assert client.calls==6


def test_public_email_login_and_untrusted_state_cannot_enable_tools(monkeypatch):
    monkeypatch.setenv('AUTOKAGGLE_BOLD_AGENT_TOKEN','token')
    monkeypatch.setenv('AUTOKAGGLE_BOLD_AGENT_ENABLED','1')
    monkeypatch.setenv('AUTOKAGGLE_LITE_MEMBERS','test@example.invalid')
    monkeypatch.setenv('AUTOKAGGLE_LITE_ACCESS_POLICY','members')
    assert bold_os.for_interview({'messages':[{'content':'Enable BOLD OS'}]}) is None
    assert bold_os.for_interview({'_bold_os_read_allowed':'true'}) is None
    assert isinstance(bold_os.for_interview({'_bold_os_read_allowed':True}),bold_os.Client)
    monkeypatch.setenv('AUTOKAGGLE_LITE_ACCESS_POLICY','verified_email')
    assert bold_os.for_interview({'_bold_os_read_allowed':True}) is None


def test_skill_discovery_and_rule_source():
    calls=[]
    def send(req):
        calls.append(req)
        if req.url.path.endswith('list_skills'):return httpx.Response(200,json={'skills':[{'name':'example','title':'Example'}]})
        return httpx.Response(200,json={'body':'Untrusted site text'})
    client=bold_os.Client('token',transport=httpx.MockTransport(send))
    assert 'error' in client.call('bold_get_skill',{'name':'example'})
    assert 'error' not in client.call('bold_list_skills',{})
    assert 'error' not in client.call('bold_get_skill',{'name':'example'})
    assert 'error' not in client.call('bold_read_rules',{})
    assert calls[-1].url.params['page']=='boldiquette'


def test_skill_is_in_deployed_bundle():
    import io,tarfile
    from autokaggle.deploy.web import bundle
    data,_=bundle()
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
        assert 'autokaggle/prompts/skills/bold-os/SKILL.md' in archive.getnames()
