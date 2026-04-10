import pytest

from chat_utils import _accumulate_thinking


class TestAccumulateThinkingCumulative:
    """累積値（前回分を含む）チャンクの処理を確認."""

    def test_first_chunk(self):
        """初回チャンクはそのまま追加される."""
        segments: list[str] = []
        _accumulate_thinking(segments, "思考中...")
        assert segments == ["思考中..."]

    def test_cumulative_replaces_last(self):
        """直前セグメントの延長は置換される."""
        segments = ["思考中..."]
        _accumulate_thinking(segments, "思考中...token1")
        assert segments == ["思考中...token1"]

    def test_cumulative_chain(self):
        """連続する累積値が正しく置換される."""
        segments: list[str] = []
        for chunk in ["ab", "abc", "abcd"]:
            _accumulate_thinking(segments, chunk)
        assert segments == ["abcd"]


class TestAccumulateThinkingDelta:
    """デルタ（今回分のみ）チャンクの処理を確認."""

    def test_delta_appended(self):
        """前回と無関係なチャンクは新セグメントとして追加される."""
        segments = ["思考中..."]
        _accumulate_thinking(segments, "[START_GATE] 開始")
        assert segments == ["思考中...", "[START_GATE] 開始"]

    def test_delta_chain(self):
        """デルタの連続は個別セグメントになる."""
        segments: list[str] = []
        for chunk in ["思考中...", "[START_GATE] 開始", "[START_GATE] 完了"]:
            _accumulate_thinking(segments, chunk)
        assert segments == ["思考中...", "[START_GATE] 開始", "[START_GATE] 完了"]


class TestAccumulateThinkingMixed:
    """累積値とデルタが混在するストリームの処理を確認."""

    def test_a2a_realistic_flow(self):
        """A2A の実際のイベント流を再現: ステータス + 累積LLMトークン."""
        segments: list[str] = []
        events = [
            "思考中...",
            "[START_GATE] 開始",
            "[START_GATE] 完了",
            "[SAMPLE] 開始",
            '{"',                       # LLM トークン開始
            '{"message',                # 累積
            '{"message":"hello"}',      # 累積
            "[SAMPLE] 完了",             # 新セグメント
            "[END_GATE] 開始",
            "[END_GATE] 完了",
        ]
        for chunk in events:
            _accumulate_thinking(segments, chunk)

        assert segments == [
            "思考中...",
            "[START_GATE] 開始",
            "[START_GATE] 完了",
            "[SAMPLE] 開始",
            '{"message":"hello"}',      # 累積トークンは最終値のみ残る
            "[SAMPLE] 完了",
            "[END_GATE] 開始",
            "[END_GATE] 完了",
        ]

    def test_api_cumulative_flow(self):
        """API の累積 thinking: 常に1セグメントで置換される."""
        segments: list[str] = []
        events = [
            "▶ START\n",
            "▶ START\ntok1",
            "▶ START\ntok1▶ SAMPLE\n",
            "▶ START\ntok1▶ SAMPLE\ntok2",
        ]
        for chunk in events:
            _accumulate_thinking(segments, chunk)

        assert segments == ["▶ START\ntok1▶ SAMPLE\ntok2"]

    def test_a2a_new_server_cumulative_flow(self):
        """A2A 新サーバー形式: API と同じ累積値で1セグメントになる."""
        segments: list[str] = []
        events = [
            "▶ START_GATE : ",
            "▶ START_GATE : \n\n▶ SAMPLE : ",
            "▶ START_GATE : \n\n▶ SAMPLE : {\"",
            "▶ START_GATE : \n\n▶ SAMPLE : {\"message\":\"hello\"}",
            "▶ START_GATE : \n\n▶ SAMPLE : {\"message\":\"hello\"}\n\n▶ SAMPLE_STREAM : ",
            "▶ START_GATE : \n\n▶ SAMPLE : {\"message\":\"hello\"}\n\n▶ SAMPLE_STREAM : こんにちは",
            "▶ START_GATE : \n\n▶ SAMPLE : {\"message\":\"hello\"}\n\n▶ SAMPLE_STREAM : こんにちは！",
            "▶ START_GATE : \n\n▶ SAMPLE : {\"message\":\"hello\"}\n\n▶ SAMPLE_STREAM : こんにちは！\n\n▶ END_GATE : ",
        ]
        for chunk in events:
            _accumulate_thinking(segments, chunk)

        # 全イベントが累積値なので1セグメントに集約される
        assert len(segments) == 1
        assert "▶ START_GATE" in segments[0]
        assert "▶ SAMPLE" in segments[0]
        assert "▶ SAMPLE_STREAM" in segments[0]
        assert "▶ END_GATE" in segments[0]
        assert "こんにちは！" in segments[0]
