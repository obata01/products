from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from langchain_core.prompts import HumanMessagePromptTemplate

import src.components.io.prompt as prompt_module
from src.components.io.prompt import load_chat_prompt


def _get_role(msg) -> str:
    """メッセージテンプレートのロール文字列を返す."""
    if isinstance(msg, HumanMessagePromptTemplate):
        return "human"
    return msg.role


@pytest.fixture
def mock_settings(tmp_path, monkeypatch):
    """settings.prompts_dir を tmp_path に差し替えるフィクスチャ."""
    mock = MagicMock()
    mock.prompts_dir = str(tmp_path)
    monkeypatch.setattr(prompt_module, "settings", mock)
    return tmp_path


def _write_template(prompts_dir: Path, filename: str, data: dict) -> None:
    path = prompts_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data))


@pytest.mark.parametrize(
    "template_data, expected_roles",
    [
        ({"system": "You are an assistant.", "human": "{input}"}, ["system", "human"]),
        ({"system": "You are an assistant."}, ["system"]),
        ({"human": "{input}"}, ["human"]),
        ({}, []),
    ],
)
def test_load_chat_prompt_builds_messages(mock_settings, template_data, expected_roles):
    """YAML の system / human キー有無に応じて ChatPromptTemplate のメッセージが構築されることを確認."""
    _write_template(mock_settings, "test.yaml", template_data)

    template = load_chat_prompt("test.yaml")

    actual_roles = [_get_role(msg) for msg in template.messages]
    assert actual_roles == expected_roles
