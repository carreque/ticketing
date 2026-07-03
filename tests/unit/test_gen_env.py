import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen_env.py"


def _load():
    spec = importlib.util.spec_from_file_location("gen_env", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen_env = _load()


# Shape of `terraform output -json`: {name: {sensitive, type, value}}
SAMPLE = {
    "api_base_url": {"sensitive": False, "type": "string",
                     "value": "https://abc.execute-api.eu-west-1.amazonaws.com"},
    "user_pool_id": {"sensitive": False, "type": "string", "value": "eu-west-1_ABC123"},
    "user_pool_client_id": {"sensitive": False, "type": "string", "value": "client123"},
    "sns_topic_arn": {"sensitive": False, "type": "string",
                      "value": "arn:aws:sns:eu-west-1:111122223333:ticketing-tickets"},
    "dynamodb_table": {"sensitive": False, "type": "string", "value": "ticketing-tickets"},
}


def test_build_env_maps_all_keys():
    assert gen_env.build_env(SAMPLE) == {
        "API_BASE_URL": "https://abc.execute-api.eu-west-1.amazonaws.com",
        "USER_POOL_ID": "eu-west-1_ABC123",
        "USER_POOL_CLIENT_ID": "client123",
        "SNS_TOPIC_ARN": "arn:aws:sns:eu-west-1:111122223333:ticketing-tickets",
        "DYNAMODB_TABLE": "ticketing-tickets",
    }


def test_build_env_missing_key_warns_and_skips(capsys):
    partial = {k: v for k, v in SAMPLE.items() if k != "sns_topic_arn"}
    env = gen_env.build_env(partial)
    assert "SNS_TOPIC_ARN" not in env
    assert len(env) == 4
    assert "sns_topic_arn" in capsys.readouterr().err


def test_render_env_has_header_and_keyvalue_lines():
    content = gen_env.render_env({"API_BASE_URL": "https://x", "USER_POOL_ID": "u"})
    lines = content.splitlines()
    assert lines[0].startswith("#")
    assert "API_BASE_URL=https://x" in lines
    assert "USER_POOL_ID=u" in lines


def test_read_outputs_parses_terraform_json(monkeypatch):
    import json
    import subprocess

    monkeypatch.setattr(gen_env, "find_terraform", lambda: "terraform")

    def fake_run(cmd, **kwargs):
        assert cmd[1:] == ["output", "-json"]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(SAMPLE), stderr="")

    monkeypatch.setattr(gen_env.subprocess, "run", fake_run)
    assert gen_env.read_outputs() == SAMPLE


def test_main_writes_env_file(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr(gen_env, "read_outputs", lambda: SAMPLE)

    gen_env.main(env_path=env_path)

    content = env_path.read_text()
    assert content.splitlines()[0].startswith("#")
    assert "API_BASE_URL=https://abc.execute-api.eu-west-1.amazonaws.com" in content
    assert "DYNAMODB_TABLE=ticketing-tickets" in content
