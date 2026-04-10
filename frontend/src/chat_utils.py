"""チャットページ共通のストリーミング表示ユーティリティ."""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from common.defs.types import ChunkType

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    StreamChunks = Generator[tuple[ChunkType, str], None, None]


def _accumulate_thinking(segments: list[str], new_chunk: str) -> None:
    """thinking チャンクをセグメントリストに蓄積する.

    直前のセグメントと比較し、新しいチャンクがその延長（累積値）であれば
    直前のセグメントを置換する。そうでなければ新しいセグメントとして追加する。
    これにより、累積値とデルタが混在するストリームの両方を正しく扱える。

    Args:
        segments: 蓄積中のセグメントリスト（直接変更される）.
        new_chunk: 新たに届いた thinking チャンク.
    """
    if segments and new_chunk.startswith(segments[-1]):
        segments[-1] = new_chunk
    else:
        segments.append(new_chunk)


class StreamingChatPage:
    """ストリーミングチャットページの共通フレームワーク.

    各ページは stream_fn（通信方法）だけを差し替えて利用する。

    Example:
        StreamingChatPage(
            title="API ストリーミング",
            session_key="api_messages",
            stream_fn=_stream_sse,
        ).run()
    """

    def __init__(
        self,
        *,
        title: str,
        session_key: str,
        stream_fn: Callable[[str], StreamChunks],
    ) -> None:
        """StreamingChatPage を初期化する.

        Args:
            title: ページタイトル.
            session_key: st.session_state に使うメッセージ履歴のキー.
            stream_fn: プロンプトを受け取り ("thinking"|"answer"|"answer_start", text)
                       を yield する関数.
        """
        self._title = title
        self._session_key = session_key
        self._stream_fn = stream_fn

    @property
    def _messages(self) -> list[dict]:
        """セッションに保存されたメッセージ履歴を返す.

        セッションに履歴が存在しない場合は空リストで初期化する。

        Returns:
            メッセージ辞書のリスト.
        """
        if self._session_key not in st.session_state:
            st.session_state[self._session_key] = []
        return st.session_state[self._session_key]

    def _append_message(
        self,
        role: str,
        content: str,
        thinking: str = "",
    ) -> None:
        """メッセージをセッション履歴に追加する.

        Args:
            role: メッセージの送信者 ("user" or "assistant").
            content: メッセージ本文.
            thinking: 思考過程テキスト. 空文字の場合は含めない.
        """
        entry: dict = {"role": role, "content": content}
        if thinking:
            entry["thinking"] = thinking
        self._messages.append(entry)

    def _render_history(self) -> None:
        """セッションに保存された過去メッセージをチャット UI として描画する.

        thinking を持つメッセージは折りたたみ可能な expander 内に表示する。
        """
        for msg in self._messages:
            with st.chat_message(msg["role"]):
                # 推論過程の表示
                if msg.get("thinking"):
                    with st.expander("推論過程"):
                        st.markdown(msg["thinking"])
                # 最終回答の表示
                st.markdown(msg["content"])

    def _render_user_message(self, prompt: str) -> None:
        """ユーザーの入力メッセージを描画し、セッションに保存する.

        Args:
            prompt: ユーザーが入力したテキスト.
        """
        self._append_message("user", prompt)
        with st.chat_message("user"):
            st.markdown(prompt)

    def _render_streaming_response(self, prompt: str) -> None:
        """stream_fn を呼び出してストリーミング表示し、セッションに保存する.

        stream_fn がエラーを送出した場合はエラーメッセージを表示・保存する。

        Args:
            prompt: ユーザーが入力したテキスト.
        """
        with st.chat_message("assistant"):
            try:
                thinking, answer = self._write_stream(self._stream_fn(prompt))
            except Exception as e:
                thinking, answer = "", f"⚠️ サービスへの接続に失敗しました: {e}"
                st.error(answer)
        self._append_message("assistant", answer, thinking)

    def _write_stream(self, chunks: StreamChunks) -> tuple[str, str]:
        """thinking / answer チャンクをリアルタイムで表示し、最終テキストを返す.

        チャンクの種別ごとに以下を行う:
        - "thinking": 思考テキストを蓄積し expander に表示
        - "answer_start": 回答バッファをクリア（新ノードの回答開始）
        - "answer": 回答テキストを追記表示

        Args:
            chunks: ("thinking"|"answer_start"|"answer", text) を yield するジェネレータ.

        Returns:
            (thinking_text, answer_text) のタプル.
        """
        thinking_segments: list[str] = []
        thinking_placeholder = st.empty()
        answer_placeholder = st.empty()
        answer_buf: list[str] = []
        answer_started = False

        for chunk_type, chunk_text in chunks:
            if chunk_type == ChunkType.THINKING:
                self._update_thinking(
                    thinking_segments, chunk_text, thinking_placeholder, answer_started,
                )
            elif chunk_type == ChunkType.ANSWER_START:
                answer_buf.clear()
                answer_placeholder.markdown("▌")
            elif chunk_type == ChunkType.ANSWER:
                answer_started = True
                answer_buf.append(chunk_text)
                answer_placeholder.markdown("".join(answer_buf) + "▌")

        return self._finalize(
            thinking_segments, thinking_placeholder, answer_buf, answer_placeholder,
        )

    @staticmethod
    def _update_thinking(
        segments: list[str],
        chunk_text: str,
        placeholder: st.delta_generator.DeltaGenerator,
        answer_started: bool,
    ) -> None:
        """thinking チャンクを蓄積し、プレースホルダーを更新する.

        回答が未開始の場合は expander を展開状態で表示し、
        回答が開始済みの場合は折りたたみ状態に切り替える。

        Args:
            segments: 蓄積中のセグメントリスト（直接変更される）.
            chunk_text: 新たに届いた thinking チャンク.
            placeholder: 思考テキスト表示用の Streamlit プレースホルダー.
            answer_started: 回答チャンクが既に届いているかどうか.
        """
        _accumulate_thinking(segments, chunk_text)
        text = "\n\n".join(segments)
        label = "思考過程" if answer_started else "思考中…"
        expanded = not answer_started
        with placeholder.expander(label, expanded=expanded):
            st.markdown(text if answer_started else text + "▌")

    @staticmethod
    def _finalize(
        thinking_segments: list[str],
        thinking_placeholder: st.delta_generator.DeltaGenerator,
        answer_buf: list[str],
        answer_placeholder: st.delta_generator.DeltaGenerator,
    ) -> tuple[str, str]:
        """ストリーム終了後にカーソルを除去して確定表示にする.

        Args:
            thinking_segments: 蓄積済みの thinking セグメントリスト.
            thinking_placeholder: 思考テキスト表示用の Streamlit プレースホルダー.
            answer_buf: 蓄積済みの回答テキスト断片リスト.
            answer_placeholder: 回答テキスト表示用の Streamlit プレースホルダー.

        Returns:
            (thinking_text, answer_text) のタプル.
        """
        thinking = "\n\n".join(thinking_segments)
        if thinking:
            with thinking_placeholder.expander("思考過程"):
                st.markdown(thinking)
        answer_text = "".join(answer_buf)
        answer_placeholder.markdown(answer_text)
        return thinking, answer_text

    def run(self) -> None:
        """ページを実行する.

        タイトル表示、メッセージ履歴の描画、ユーザー入力の受付、
        ストリーミング表示、セッションへの保存を順に行う。
        """
        st.title(self._title)
        self._render_history()

        if prompt := st.chat_input("メッセージを入力"):
            self._render_user_message(prompt)
            self._render_streaming_response(prompt)
