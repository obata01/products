import pytest
from a2a.types import AgentCard

from src.a2a_app.card import build_agent_card


@pytest.mark.parametrize("url", [
    "http://localhost:8000/a2a",
    "http://other-agent.example.com/a2a",
])
def test_build_agent_card_url(url):
    """URL が AgentCard に正しく設定されることを確認."""
    card = build_agent_card(url)

    assert card.url == url


def test_build_agent_card_returns_agent_card():
    """戻り値が AgentCard インスタンスであることを確認."""
    card = build_agent_card("http://localhost:8000/a2a")

    assert isinstance(card, AgentCard)


def test_build_agent_card_streaming_enabled():
    """streaming capability が有効化されていることを確認."""
    card = build_agent_card("http://localhost:8000/a2a")

    assert card.capabilities.streaming is True


def test_build_agent_card_has_chat_skill():
    """chat スキルが含まれることを確認."""
    card = build_agent_card("http://localhost:8000/a2a")

    assert any(s.id == "chat" for s in card.skills)
