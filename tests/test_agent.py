import sys

from opayai import agent


def test_server_params_use_active_python_and_disable_demo_notifications(monkeypatch):
    monkeypatch.delenv("OPAYAI_NOTIFY", raising=False)
    params = agent.server_params()
    assert params["command"] == sys.executable
    assert params["args"] == ["-m", "opayai.server"]
    assert params["env"]["OPAYAI_NOTIFY"] == "0"


def test_model_can_be_overridden(monkeypatch):
    monkeypatch.setenv("OPAYAI_OPENAI_MODEL", "test-model")
    assert agent.model_name() == "test-model"


def test_prompt_arguments_are_joined_by_main_parser():
    args = agent.parse_args(["buy", "a", "monitor"])
    assert args.prompt == ["buy", "a", "monitor"]
