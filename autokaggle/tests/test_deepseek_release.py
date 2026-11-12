from autokaggle import lite_evaluator_cli

def test_failure_diagnostics_do_not_repeat_execution(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("A failed seed must not execute again")
    monkeypatch.setattr(lite_evaluator_cli.subprocess, "run", forbidden)
    lite_evaluator_cli.explain({"seed": 1, "status": "failed"}, {}, {"timeout_seconds": 1})
    assert "No automatic retry" in capsys.readouterr().err


def test_deepseek_deployment_secret_and_model_settings(tmp_path, monkeypatch):
    from autokaggle.deploy import web, lite_web
    path = tmp_path / "model.env"
    path.write_text("DEEPSEEK_API_KEY=test-deepseek-key\n")
    monkeypatch.setattr(web, "PRIVATE_ENV", tmp_path / "full.env")
    monkeypatch.setattr(lite_web, "PRIVATE_ENV", tmp_path / "lite.env")
    monkeypatch.setattr(lite_web, "GITHUB_ENV", tmp_path / "absent.env")
    for module in (web, lite_web):
        private = module.private_settings(path)
        assert private["DEEPSEEK_API_KEY"] == private["OPENAI_API_KEY"] == "test-deepseek-key"
        assert "OPENROUTER_API_KEY" not in private
        resources = module.resources(b"source", "a" * 64, private, ["192.0.2.1"])
        config = next(item["data"] for item in resources if item["kind"] == "ConfigMap" and item["metadata"]["name"].endswith("-config"))
        assert config["OPENAI_BASE_URL"] == "https://api.deepseek.com"
        assert config["AUTOKAGGLE_MODEL"] == "deepseek-v4-pro"
        assert "DEEPSEEK_API_KEY" not in config


def test_deepseek_full_has_room_for_reasoning_and_structured_answer(monkeypatch):
    from autokaggle import conversation
    from autokaggle.tests.test_conversation import provider, scope
    monkeypatch.setenv('OPENAI_BASE_URL','https://api.deepseek.com')
    calls=provider(monkeypatch,[scope([], 'data', 'Which environment should be used?')])
    project={'title':'Test','answers':{},'design':{},'_model_calls':0}
    conversation.submit_message(project,'Measure NetHack ascension.','budget-test')
    assert calls[0]['max_output_tokens']==32768
    assert calls[0]['reasoning']=={'effort':'medium'}


def test_token_push_updates_only_requested_refs(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from autokaggle.lite_publish import TokenGitHub
    repo=tmp_path/'repo';repo.mkdir()
    subprocess.run(['git','init','-q',str(repo)],check=True)
    subprocess.run(['git','-C',str(repo),'-c','user.name=Test','-c','user.email=test@example.org','commit','--allow-empty','-qm','test'],check=True)
    commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    class Client:
        def send_pack(self,path,update,**kwargs):
            remote={b'HEAD':commit.encode(),b'refs/heads/main':commit.encode(),b'refs/tags/v1':commit.encode()}
            assert update(remote)=={b'refs/tags/v2':commit.encode()}
            return SimpleNamespace(ref_status={})
    hub=TokenGitHub('test-only')
    monkeypatch.setattr(hub,'_remote',lambda repository:(Client(),b'repo'))
    hub.push(repo,{'full_name':'test/repo'},['refs/tags/v2'],{'refs/tags/v2':commit},{'HEAD':commit,'refs/heads/main':commit,'refs/tags/v1':commit})
