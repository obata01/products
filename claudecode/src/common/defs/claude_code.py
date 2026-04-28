"""Claude Code CLI の stream-json 出力スキーマに対応する型定義.

`claude -p ... --output-format stream-json --verbose` を実行したときに
1 行 1 JSON で吐き出される各イベントのフィールド値を表す。

Note:
    - 値は Claude Code CLI 側の仕様に準拠しており、本アプリで独自に定義したものではない.
    - CLI のバージョンアップで値が追加・変更される可能性がある.
    - アプリ側で扱わない値は ignore-by-default の方針で無視する.
"""

from enum import StrEnum


class ClaudeCodeEventType(StrEnum):
    """stream-json 各行の `type` フィールドの値.

    Note:
        - CLI が吐く主要な type のうち、本アプリで参照するものを列挙する.
        - CLI 仕様上は他にも `user` / `tool_result` などが存在するが、
          現時点ではアプリ側で利用していないため未定義.
    """

    SYSTEM = "system"
    ASSISTANT = "assistant"
    TOOL_USE = "tool_use"
    RESULT = "result"


class ClaudeCodeSystemSubtype(StrEnum):
    """`type == "system"` イベントの `subtype` フィールドの値."""

    INIT = "init"


class ClaudeCodeContentBlockType(StrEnum):
    """assistant メッセージの content block の `type` フィールドの値.

    `event["message"]["content"]` の各要素に含まれる。
    """

    TEXT = "text"
