"""他の A2A エージェントと通信するための汎用クライアントモジュール.

特定サーバーのレスポンス解釈には依存しない。
サーバー固有の変換ロジックは services 配下に配置すること。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import httpx
from a2a.client import A2ACardResolver, Client
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.client.helpers import create_text_message_object
from a2a.types import (
    Artifact,
    Message,
    Part,
)


def text_from_parts(parts: list[Part]) -> str:
    """Part リストからテキストを連結して返す.

    Args:
        parts: A2A メッセージのパーツリスト.

    Returns:
        テキストパーツを結合した文字列.
    """
    return "".join(p.root.text for p in parts if hasattr(p.root, "text") and p.root.text)


def text_from_message(message: Message) -> str:
    """Message からテキストを抽出する.

    Args:
        message: A2A メッセージ.

    Returns:
        メッセージのテキスト.
    """
    return text_from_parts(message.parts)


def text_from_artifact(artifact: Artifact) -> str:
    """Artifact からテキストを抽出する.

    Args:
        artifact: A2A タスクの成果物.

    Returns:
        成果物のテキスト.
    """
    return text_from_parts(artifact.parts)


class AgentClient:
    """他の A2A エージェントと通信する汎用クライアント.

    async with 構文でライフサイクルを管理し、内部の httpx セッションを共有する。
    A2A プロトコルの生イベントをそのまま返す。
    サーバー固有のイベント解釈はこのクラスの責任外。

    Example:
        async with AgentClient("http://other-agent/a2a") as client:
            async for event in client.stream_events("こんにちは"):
                print(event)
    """

    def __init__(self, base_url: str) -> None:
        """AgentClient を初期化する.

        Args:
            base_url: 接続先エージェントの A2A サーバー URL。
        """
        self._base_url = base_url
        self._httpx_client: httpx.AsyncClient | None = None
        self._factory: ClientFactory | None = None

    async def __aenter__(self) -> Self:
        """Httpx クライアントを初期化して自身を返す."""
        self._httpx_client = await httpx.AsyncClient().__aenter__()
        config = ClientConfig(httpx_client=self._httpx_client, streaming=True)
        self._factory = ClientFactory(config=config)
        return self

    async def __aexit__(self, *args: object) -> None:
        """Httpx クライアントを閉じる."""
        if self._httpx_client:
            await self._httpx_client.__aexit__(*args)

    async def stream_events(self, text: str) -> AsyncGenerator[Any]:
        """テキストメッセージを送信し、A2A の生イベントを yield する.

        Args:
            text: 送信するテキストメッセージ.

        Yields:
            A2A プロトコルの生イベント。具体的な型はサーバー実装に依存する。
        """
        client = await self._resolve_client()
        message = create_text_message_object(content=text)

        async for event in client.send_message(message):
            yield event

    async def _resolve_client(self) -> Client:
        """エージェントカードを解決して Client を生成する.

        Returns:
            初期化済みの A2A Client.

        Raises:
            A2AClientHTTPError: カード取得に失敗した場合.
        """
        resolver = A2ACardResolver(httpx_client=self._httpx_client, base_url=self._base_url)
        agent_card = await resolver.get_agent_card()
        return self._factory.create(card=agent_card)
