はい。Agent SDK で書くと、**subprocess 管理と stream-json の手動パースがほぼ不要**になります。
代わりに、`query(...)` を `async for` で回して、SDK が返す `StreamEvent`、`AssistantMessage`、`ResultMessage` を直接処理する形になります。Agent SDK は Claude Code と同じツール、agent loop、context management を Python/TypeScript から使えるライブラリで、`include_partial_messages=True` にするとリアルタイムの `StreamEvent` が流れます。([Claude API Docs][1])

あなたの今のコードとの対応はこうです。

* `asyncio.create_subprocess_exec(...)`
  → `query(prompt=..., options=...)`
* `proc.stdout` を1行ずつ JSON パース
  → `StreamEvent.event` を見る
* `system/init` / `assistant` / `result` を自前で判定
  → `SystemMessage` / `StreamEvent` / `AssistantMessage` / `ResultMessage` を `isinstance()` で判定
* `stderr drain`
  → 不要
* CLI の permissions や `.claude` 設定
  → `ClaudeAgentOptions(...)` と SDK 側設定で管理。SDK は既定で `.claude/` と `~/.claude/` の設定も読み込めます。([Claude][2])

---

## まず最小の骨格

公式の最小例はこういう形です。

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    async for message in query(
        prompt="Find and fix the bug in auth.py",
        options=ClaudeAgentOptions(allowed_tools=["Read", "Edit", "Bash"]),
    ):
        print(message)

asyncio.run(main())
```

これは SDK の基本パターンです。`query(...)` が async iterable を返し、そこに各種メッセージが流れてきます。([Claude API Docs][1])

---

## あなたの今の用途に寄せると

いま欲しいのはたぶんこれです。

* LangGraph ノードの中で呼びたい
* トークンを逐次 dispatch したい
* 進捗も dispatch したい
* 最終的に `AIMessage(content=...)` を返したい

その場合、だいたいこうなります。

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    SystemMessage,
    AssistantMessage,
    ResultMessage,
)
from claude_agent_sdk.types import StreamEvent
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage

from src.application.stream import CLAUDE_CODE_PROGRESS_EVENT, CLAUDE_CODE_TOKEN_EVENT

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from src.application.states import State


_ERROR_MESSAGE = "Claude Agent SDK の処理中にエラーが発生しました。"


async def _dispatch_token(delta: str, config: RunnableConfig) -> None:
    await adispatch_custom_event(
        CLAUDE_CODE_TOKEN_EVENT,
        {"text": delta},
        config=config,
    )


async def _dispatch_progress(message: str, config: RunnableConfig) -> None:
    await adispatch_custom_event(
        CLAUDE_CODE_PROGRESS_EVENT,
        {"message": message},
        config=config,
    )


def _build_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        include_partial_messages=True,
        # 必要なものだけ許可
        allowed_tools=["Read", "Glob", "Grep"],
        # 例: 既存の .claude 設定を読むならそのまま
        # setting_sources=["project", "user"],
        # 例: セッション継続したいなら resume=...
    )


async def claude_agent_node(state: State, config: RunnableConfig) -> dict:
    prompt = state["last_user_message"]
    options = _build_options()

    full_text = ""

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, SystemMessage):
                # init などの system メッセージ
                if getattr(message, "subtype", None) == "init":
                    await _dispatch_progress("Claude Agent セッション開始", config)

            elif isinstance(message, StreamEvent):
                event = message.event
                event_type = event.get("type")

                # 逐次テキスト
                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            full_text += text
                            await _dispatch_token(text, config)

                # ツール進捗も拾える
                elif event_type == "content_block_start":
                    content_block = event.get("content_block", {})
                    if content_block.get("type") == "tool_use":
                        tool_name = content_block.get("name", "")
                        if tool_name:
                            await _dispatch_progress(f"ツール実行中: {tool_name}", config)

            elif isinstance(message, AssistantMessage):
                # 完成済み1ターン分の assistant メッセージ
                # partial を使っていれば、通常は full_text は StreamEvent で組み立て済み
                pass

            elif isinstance(message, ResultMessage):
                # 最終結果
                if getattr(message, "subtype", None) == "success":
                    if getattr(message, "result", None):
                        # 念のため result を優先したいならここで上書き可能
                        full_text = message.result
                else:
                    if not full_text:
                        full_text = _ERROR_MESSAGE

    except Exception:
        if not full_text:
            full_text = _ERROR_MESSAGE

    return {
        "chat_history": [AIMessage(content=full_text or _ERROR_MESSAGE)],
    }
```

---

## このコードで何が変わるか

いちばん大きい違いは、**イベントの解釈単位**です。

### CLI 版

あなたがやっていたのは、

* stdout から JSONL を読む
* `type == "assistant"` かを見る
* `content` から text を抜く
* 前回長との差分をとる

でした。

### Agent SDK 版

SDK の streaming は、`include_partial_messages=True` を付けると `StreamEvent` が流れ、そこに raw Claude API stream event が入っています。テキストをリアルタイムで取りたい場合は、`content_block_delta` かつ `delta.type == "text_delta"` を見ます。SDK docs もこの処理パターンを案内しています。([Claude][2])

つまり差分計算はこう変わります。

* CLI 版: 完全文から `prev_len` で差分を切る
* SDK 版: そもそも `text_delta` が差分で流れてくるので、そのまま dispatch できる

ここは SDK 版のほうがきれいです。([Claude][2])

---

## 進捗イベントはどう拾うか

進捗は2系統で拾えます。

### 1. セッション開始

`SystemMessage` の `subtype == "init"` で取れます。SDK docs の sessions 例でも、Python では `SystemMessage` の `data` から `session_id` を読む形が出ています。([Claude API Docs][1])

### 2. ツール利用開始

`StreamEvent` の `content_block_start` で、`content_block.type == "tool_use"` を見れば取れます。SDK の streaming docs に tool call の追跡例があります。([Claude][2])

なので、あなたの今の

* `"Claude Code セッション開始"`
* `"ツール実行中: ..."`

のような progress dispatch は、そのまま再現しやすいです。([Claude][2])

---

## 最終結果はどこで取るか

SDK では、partial streaming を有効にしていても、最後に `ResultMessage` が来ます。さらに `AssistantMessage` は「1ターン分の完成メッセージ」、`ResultMessage` は「最終結果」です。message flow と agent loop docs にその説明があります。([Claude][2])

なので設計としては、

* **SSE 用の逐次表示**
  → `StreamEvent` の `text_delta`
* **最終保存用の本文**
  → `ResultMessage.result`

にすると安定しやすいです。([Claude][2])

---

## いまの subprocess 版より良い点

Agent SDK に寄せると、主にこの点が楽になります。

### 1. subprocess 管理が消える

`create_subprocess_exec`、`stderr` drain、`returncode`、タイムアウト後の `kill()` などが不要になります。SDK 側の agent loop を直接使う形です。([Claude API Docs][1])

### 2. イベントが意味付きで来る

`StreamEvent`、`AssistantMessage`、`ResultMessage`、`SystemMessage` のように型付きで扱えます。([Claude][2])

### 3. Claude Code の機能をそのまま使える

SDK には built-in tools、hooks、subagents、MCP、permissions、sessions があり、CLI 相当の能力をライブラリ化して使えます。([Claude API Docs][1])

### 4. セッション継続がしやすい

`resume=session_id` で継続できます。Python では `SystemMessage.data["session_id"]` か `ResultMessage.session_id` を使う流れが docs にあります。([Claude API Docs][1])

---

## 逆に注意点

### 1. streaming の粒度は CLI と少し違う

SDK の partial streaming は raw Claude API events に近いので、`content_block_delta` / `text_delta` を見る必要があります。CLI の `assistant.message.content` 完全文とは粒度が違います。([Claude][2])

### 2. `include_partial_messages=True` が必要

デフォルトでは完全な `AssistantMessage` がターン完了後に来ます。リアルタイム token を欲しいなら partial messages を有効にする必要があります。([Claude][2])

### 3. thinking を明示有効化すると stream event が出ない場合がある

SDK docs では、`max_thinking_tokens` を明示設定すると `StreamEvent` が出ず、完全メッセージのみになるとあります。([Claude][2])

---

## LangGraph とのつなぎ方のイメージ

ここは今までと同じです。
違うのは、**イベント源が subprocess stdout ではなく SDK iterator** になるだけです。

```text
FastAPI
  ↓
LangGraph
  ↓
claude_agent_node(...)
  ↓
async for message in query(...)
  ↓
StreamEvent / SystemMessage / ResultMessage
  ↓
adispatch_custom_event(...)
  ↓
LangGraph astream_events(...)
  ↓
SSE
```

つまり、親の Python プロセスがイベントループ上で

* Agent SDK からのメッセージ受信
* LangGraph custom event dispatch
* SSE 送信

を切り替えながら進める、という構造は同じです。違うのは「Claude との接続方法」だけです。Agent SDK は built-in の agent loop を提供し、SDK の `query(...)` を async iterator として処理します。([Claude API Docs][1])

---

## どちらが向いているか

### CLI subprocess のままが向く

* すでに CLI ベース実装が安定している
* ローカル開発環境の Claude Code と同じ振る舞いを優先したい
* まず最小変更で API 化したい

### Agent SDK が向く

* 本番サービスとして Python から直接使いたい
* subprocess 管理をやめたい
* sessions / hooks / custom tools / MCP / subagents をコードから扱いたい
* LangGraph との統合をもっときれいにしたい

Anthropic 公式も、CLI は日常開発、SDK は custom applications / production automation に向くと整理しています。([Claude API Docs][1])

---

## 一番短くまとめると

Agent SDK 版では、**`query(...)` を `async for` で回して、`StreamEvent` の `text_delta` をそのまま LangGraph の custom event に流す**形になります。
その結果、

* subprocess 起動
* stdout/stderr パース
* 差分計算

がかなり薄くなります。([Claude][2])

必要なら次に、**あなたが貼ってくれた現在の `claude_code(...)` を、Agent SDK 版へほぼ同じ責務で完全に書き換えたサンプル**をもう少し実装寄りに出せます。

[1]: https://docs.anthropic.com/en/docs/claude-code/sdk "Agent SDK overview - Claude Code Docs"
[2]: https://code.claude.com/docs/en/agent-sdk/streaming-output "Stream responses in real-time - Claude Code Docs"
