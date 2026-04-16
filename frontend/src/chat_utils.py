"""チャットページ共通のストリーミング表示ユーティリティ."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import streamlit as st

from common.defs.types import ChunkType

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    StreamChunks = Generator[tuple[ChunkType, str], None, None]


_LABEL_THINKING = "推論過程"
_LABEL_THINKING_ACTIVE = "推論中…"


class InputRequiredInterrupt(Exception):
    """ストリーム中に INPUT_REQUIRED チャンクを受信したことを示す例外."""

    def __init__(self, metadata: dict, thinking: str, answer: str) -> None:
        self.metadata = metadata
        self.thinking = thinking
        self.answer = answer
        super().__init__()


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
                    with st.expander(_LABEL_THINKING):
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

    def _render_streaming_response(
        self,
        prompt: str,
        prior_thinking: str = "",
    ) -> None:
        """stream_fn を呼び出してストリーミング表示し、セッションに保存する.

        stream_fn がエラーを送出した場合はエラーメッセージを表示・保存する。
        INPUT_REQUIRED を受信した場合はセッションに確認待ち状態を保存し、
        メッセージ履歴には追加せずに rerun する。

        Args:
            prompt: ユーザーが入力したテキスト.
            prior_thinking: 前段ノードで蓄積済みの思考過程テキスト.
        """
        with st.chat_message("assistant"):
            try:
                thinking, answer = self._write_stream(
                    self._stream_fn(prompt), prior_thinking,
                )
            except InputRequiredInterrupt as ir:
                st.session_state[f"{self._session_key}_interrupted_thinking"] = ir.thinking
                self._set_pending_confirm(ir.metadata)
                st.rerun()
            except Exception as e:
                thinking, answer = "", f"⚠️ サービスへの接続に失敗しました: {e}"
                st.error(answer)
        self._append_message("assistant", answer, thinking)

    def _set_pending_confirm(self, metadata: dict) -> None:
        """確認待ち状態をセッションに保存する."""
        st.session_state[f"{self._session_key}_pending_confirm"] = metadata

    def _restore_resume_context(self, metadata: dict) -> None:
        """resume に必要なコンテキスト情報を metadata からセッションに復元する.

        プロトコル固有のキー (例: A2A の context_id) を
        stream_fn が参照できるようセッションステートにセットする。
        """
        if context_id := metadata.get("context_id"):
            st.session_state["a2a_context_id"] = context_id

    def _clear_pending_confirm(self) -> None:
        """確認待ち状態をセッションから削除する."""
        st.session_state.pop(f"{self._session_key}_pending_confirm", None)

    def _get_pending_confirm(self) -> dict | None:
        """確認待ち状態をセッションから取得する."""
        return st.session_state.get(f"{self._session_key}_pending_confirm")

    def _render_confirm_ui(self, metadata: dict) -> None:
        """確認 UI を表示し、ユーザーの選択に応じてセッション状態を更新して rerun する.

        前段ノードの thinking がある場合は assistant メッセージとして表示する。
        ボタンハンドラ内ではセッション状態の更新のみ行い、
        実際のストリーミング描画は run() のトップレベルで実行する。

        Args:
            metadata: input_required イベントの metadata.
        """
        thinking_key = f"{self._session_key}_interrupted_thinking"
        prior_thinking = st.session_state.get(thinking_key, "")
        message = metadata.get("message", "確認が必要です。")
        preview = metadata.get("preview")

        if prior_thinking:
            with st.chat_message("assistant"):
                with st.expander(_LABEL_THINKING, expanded=False):
                    st.markdown(prior_thinking)

        with st.container(border=True):
            st.warning(message)
            if preview:
                with st.expander("プレビュー", expanded=True):
                    st.markdown(preview)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("承認", type="primary", key=f"{self._session_key}_approve"):
                    self._clear_pending_confirm()
                    self._restore_resume_context(metadata)
                    st.session_state[f"{self._session_key}_resume"] = "yes"
                    st.session_state[f"{self._session_key}_prior_thinking"] = prior_thinking
                    st.rerun()
            with col2:
                if st.button("拒否", key=f"{self._session_key}_reject"):
                    self._clear_pending_confirm()
                    self._restore_resume_context(metadata)
                    st.session_state[f"{self._session_key}_resume"] = "no"
                    st.rerun()

    def _write_stream(
        self,
        chunks: StreamChunks,
        prior_thinking: str = "",
    ) -> tuple[str, str]:
        """thinking / answer チャンクをリアルタイムで表示し、最終テキストを返す.

        チャンクの種別ごとに以下を行う:
        - "thinking": 思考テキストを蓄積し expander に表示
        - "answer_start": 回答バッファをクリア（新ノードの回答開始）
        - "answer": 回答テキストを追記表示
        - "input_required": 確認待ちとして InputRequiredInterrupt を送出

        Args:
            chunks: ("thinking"|"answer_start"|"answer"|"input_required", text)
                    を yield するジェネレータ.
            prior_thinking: 前段ノードで蓄積済みの思考過程テキスト.

        Returns:
            (thinking_text, answer_text) のタプル.

        Raises:
            InputRequiredInterrupt: INPUT_REQUIRED チャンクを受信した場合.
        """
        thinking_segments: list[str] = []
        if prior_thinking:
            thinking_segments.append(prior_thinking)
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
            elif chunk_type == ChunkType.INPUT_REQUIRED:
                thinking, answer = self._finalize(
                    thinking_segments, thinking_placeholder,
                    answer_buf, answer_placeholder,
                )
                metadata = json.loads(chunk_text) if chunk_text else {}
                raise InputRequiredInterrupt(metadata, thinking, answer)

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
        label = _LABEL_THINKING if answer_started else _LABEL_THINKING_ACTIVE
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
            with thinking_placeholder.expander(_LABEL_THINKING):
                st.markdown(thinking)
        answer_text = "".join(answer_buf)
        answer_placeholder.markdown(answer_text)
        return thinking, answer_text

    def run(self) -> None:
        """ページを実行する.

        タイトル表示、メッセージ履歴の描画、ユーザー入力の受付、
        ストリーミング表示、セッションへの保存を順に行う。
        確認待ち状態がある場合は確認 UI を、
        resume 待ちの場合は resume ストリーミングを表示する。
        """
        st.title(self._title)
        self._render_history()

        if metadata := self._get_pending_confirm():
            self._render_confirm_ui(metadata)
            return

        resume_key = f"{self._session_key}_resume"
        if resume_prompt := st.session_state.pop(resume_key, None):
            prior_thinking = st.session_state.pop(
                f"{self._session_key}_prior_thinking", "",
            )
            self._render_streaming_response(resume_prompt, prior_thinking)

        if prompt := st.chat_input("メッセージを入力"):
            self._render_user_message(prompt)
            self._render_streaming_response(prompt)
