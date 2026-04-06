"""他の A2A エージェントと通信するためのクライアントモジュール."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

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
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
)

# thinking: 思考中の中間テキスト / answer: 最終回答テキスト
StreamChunk = tuple[Literal["thinking", "answer"], str]


def _text_from_parts(parts: list[Part]) -> str:
    """Part リストからテキストを連結して返す.

    Args:
        parts: A2A メッセージのパーツリスト.

    Returns:
        テキストパーツを結合した文字列.
    """
    return "".join(p.root.text for p in parts if hasattr(p.root, "text") and p.root.text)


def _text_from_message(message: Message) -> str:
    """Message からテキストを抽出する.

    Args:
        message: A2A メッセージ.

    Returns:
        メッセージのテキスト.
    """
    return _text_from_parts(message.parts)


def _text_from_artifact(artifact: Artifact) -> str:
    """Artifact からテキストを抽出する.

    Args:
        artifact: A2A タスクの成果物.

    Returns:
        成果物のテキスト.
    """
    return _text_from_parts(artifact.parts)


class AgentClient:
    """他の A2A エージェントと通信するクライアント.

    async with 構文でライフサイクルを管理し、内部の httpx セッションを共有する。

    Example:
        async with AgentClient("http://other-agent/a2a") as client:
            result = await client.send("こんにちは")

            async for chunk_type, text in client.stream("こんにちは"):
                print(chunk_type, text)
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

    async def send(self, text: str) -> str:
        """テキストメッセージを送信して最終回答を返す.

        Args:
            text: 送信するテキストメッセージ.

        Returns:
            エージェントの最終回答テキスト.
        """
        answer = ""
        async for chunk_type, chunk_text in self.stream(text):
            if chunk_type == "answer":
                answer = chunk_text
        return answer

    async def stream(self, text: str) -> AsyncGenerator[StreamChunk]:
        """テキストメッセージを送信し、思考と最終回答を StreamChunk としてストリーミングする.

        Args:
            text: 送信するテキストメッセージ.

        Yields:
            ("thinking", テキスト) または ("answer", テキスト) のタプル.

        Note:
            thinking テキストは累積値として届く場合がある（サーバー実装に依存）.
        """
        client = await self._resolve_client()
        message = create_text_message_object(content=text)

        async for event in client.send_message(message):
            match event:
                case (_, TaskStatusUpdateEvent() as ev) if (
                    ev.status.state == TaskState.working and ev.status.message
                ):
                    thinking = _text_from_message(ev.status.message)
                    if thinking:
                        yield "thinking", thinking

                case (_, TaskArtifactUpdateEvent() as ev):
                    answer = _text_from_artifact(ev.artifact)
                    if answer:
                        yield "answer", answer

                case Message() as msg:
                    answer = _text_from_message(msg)
                    if answer:
                        yield "answer", answer

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
