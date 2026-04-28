from pathlib import Path

import yaml
from langchain_core.prompts import ChatMessagePromptTemplate, ChatPromptTemplate, HumanMessagePromptTemplate

from src.common.settings.app import settings


def load_chat_prompt(template_file: str) -> ChatPromptTemplate:
    """プロンプトテンプレートファイルを読み込んで ChatPromptTemplate を返す.

    テンプレートは YAML 形式で、system / human キーに対応するメッセージを定義する。

    Args:
        template_file: settings.prompts_dir を起点とする相対パス (例: "nodes/sample.lc.tpl").

    Returns:
        ChatPromptTemplate のインスタンス.
    """
    path = Path(settings.prompts_dir) / template_file
    with open(path) as f:
        data = yaml.safe_load(f)

    messages = []
    if "system" in data:
        messages.append(ChatMessagePromptTemplate.from_template(data["system"], role="system"))
    if "human" in data:
        messages.append(HumanMessagePromptTemplate.from_template(data["human"]))

    return ChatPromptTemplate.from_messages(messages)
