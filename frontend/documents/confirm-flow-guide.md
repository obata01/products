# ユーザー確認フロー (Confirm / Interrupt) 実装ガイド

フロントエンドでユーザー確認 (CONFIRM ノード) を実装するためのガイド。
バックエンドの仕組み、イベント仕様、フロントエンドの実装パターンを説明する。

---

## 目次

- [概要](#概要)
- [ワークフロー全体像](#ワークフロー全体像)
- [イベントシーケンス](#イベントシーケンス)
  - [HTTP SSE の場合](#http-sse-の場合)
  - [A2A の場合](#a2a-の場合)
- [input_required イベントの詳細](#input_required-イベントの詳細)
- [ユーザー応答 (Resume) の送信](#ユーザー応答-resume-の送信)
  - [HTTP SSE の場合](#http-sse-の場合-1)
  - [A2A の場合](#a2a-の場合-1)
- [承認ワード一覧](#承認ワード一覧)
- [フロントエンド実装パターン](#フロントエンド実装パターン)
  - [基本フロー](#基本フロー)
  - [HTTP SSE 実装例 (Python)](#http-sse-実装例-python)
  - [HTTP SSE 実装例 (TypeScript)](#http-sse-実装例-typescript)
- [中断 (Abort) 時の挙動](#中断-abort-時の挙動)

---

## 概要

バックエンドの CONFIRM ノードは LangGraph の `interrupt()` を使ってワークフローを一時停止し、
フロントエンドにユーザーの承認を求める。

フロントエンドは以下を実装する必要がある:

1. `input_required` イベントを検知する
2. ユーザーに確認 UI を表示する (メッセージ + プレビュー)
3. ユーザーの応答 (承認 or 中断) を **同じ session_id** で再送信する

---

## ワークフロー全体像

```
START → SAMPLE (分析) → CONFIRM (確認待ち) → SAMPLE_STREAM (回答生成) → END
                              │
                              └─ [中断された場合] → END
```

CONFIRM ノードで `interrupt()` が呼ばれると、ワークフローが一時停止する。
フロントエンドからの応答で再開 (resume) され、承認なら次のノードへ進み、中断なら終了する。

---

## イベントシーケンス

### HTTP SSE の場合

**正常フロー (承認):**

```
── 初回リクエスト ──────────────────────
data: {"type":"node_start","node":"SAMPLE","label":"分析中"}
data: {"type":"token","node":"SAMPLE","label":"分析中","content":"..."}
data: {"type":"node_end","node":"SAMPLE","label":"分析中"}
data: {"type":"node_start","node":"CONFIRM","label":"確認待ち"}
data: {"type":"node_end","node":"CONFIRM","label":"確認待ち"}
data: {"type":"input_required","metadata":{"message":"この内容で...","preview":"..."}}
data: {"type":"done","session_id":"abc123","message":""}
── ストリーム終了 ──────────────────────

    [フロントエンドが確認 UI を表示]
    [ユーザーが「承認」を選択]

── 再リクエスト (同じ session_id, message="yes") ──
data: {"type":"node_start","node":"SAMPLE_STREAM","label":"回答生成中"}
data: {"type":"token","node":"SAMPLE_STREAM","label":"回答生成中","content":"こんにちは"}
data: {"type":"node_end","node":"SAMPLE_STREAM","label":"回答生成中"}
data: {"type":"done","session_id":"abc123","message":"最終回答テキスト"}
── ストリーム終了 ──────────────────────
```

**中断フロー:**

```
── 初回リクエスト (SAMPLE → CONFIRM、上記と同じ) ──
...
data: {"type":"input_required","metadata":{"message":"...","preview":"..."}}
data: {"type":"done","session_id":"abc123","message":""}
── ストリーム終了 ──────────────────────

    [ユーザーが「中断」を選択]

── 再リクエスト (同じ session_id, message="no") ──
data: {"type":"done","session_id":"abc123","message":"ユーザーにより中断されました。"}
── ストリーム終了 ──────────────────────
```

### A2A の場合

**正常フロー (承認):**

```
── 初回リクエスト ──────────────────────
TaskStatusUpdateEvent (working): {"type":"node_start","node":"SAMPLE","label":"分析中"}
TaskStatusUpdateEvent (working): {"type":"token","node":"SAMPLE",...}
TaskStatusUpdateEvent (working): {"type":"node_end","node":"SAMPLE","label":"分析中"}
TaskStatusUpdateEvent (working): {"type":"node_start","node":"CONFIRM","label":"確認待ち"}
TaskStatusUpdateEvent (working): {"type":"node_end","node":"CONFIRM","label":"確認待ち"}
TaskStatusUpdateEvent (input_required): "ユーザーの確認を待っています。"
── ストリーム終了 ──────────────────────

    [ユーザーが「承認」を選択]

── 再リクエスト (同じ context_id, message="yes") ──
TaskStatusUpdateEvent (working): {"type":"node_start","node":"SAMPLE_STREAM",...}
TaskStatusUpdateEvent (working): {"type":"token","node":"SAMPLE_STREAM",...}
TaskStatusUpdateEvent (working): {"type":"node_end","node":"SAMPLE_STREAM",...}
TaskArtifactUpdateEvent: "最終回答テキスト"
TaskStatusUpdateEvent (completed, final=true)
── ストリーム終了 ──────────────────────
```

---

## input_required イベントの詳細

### HTTP SSE

```json
{
  "type": "input_required",
  "metadata": {
    "message": "この内容で回答を生成してよろしいですか？",
    "preview": "SAMPLE ノードの出力プレビュー (AI の分析結果)"
  }
}
```

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `type` | `"input_required"` | ユーザー確認が必要であることを示す |
| `metadata.message` | string | ユーザーに表示する確認メッセージ |
| `metadata.preview` | string | 前段ノード (SAMPLE) の出力プレビュー |

### A2A

```json
{
  "status": {
    "state": "input_required",
    "message": {
      "role": "agent",
      "parts": [{"type": "text", "text": "ユーザーの確認を待っています。"}]
    }
  },
  "final": false,
  "taskId": "...",
  "contextId": "..."
}
```

A2A では `input_required` は `TaskStatusUpdateEvent` の `status.state` として送信される。
confirm ノードの `metadata` (message, preview) は、直前の `working` イベントで `StreamEvent` として配信済み。

---

## ユーザー応答 (Resume) の送信

### HTTP SSE の場合

同じ `session_id` で `/test` エンドポイントに再度 POST する。
バックエンドは `session_id` から中断中のワークフローを検出し、自動的に resume する。

```http
POST /test
Content-Type: application/json

{
  "session_id": "abc123",
  "message": "yes",
  "stream": true
}
```

- `session_id`: 初回リクエストと同じ値 (必須)
- `message`: 承認ワードまたは任意のテキスト
- `stream`: 初回と同じ設定を推奨

### A2A の場合

同じ `context_id` (または `task_id`) で `message/stream` (または `message/send`) を再リクエストする。

---

## 承認ワード一覧

以下の文字列 (大文字小文字不問) が承認として扱われる。それ以外は中断として扱われる。

| 言語 | 承認ワード |
|------|-----------|
| 英語 | `yes`, `approve`, `ok` |
| 日本語 | `はい`, `承認` |

---

## フロントエンド実装パターン

### 基本フロー

```
1. ユーザーがメッセージを送信
2. SSE ストリームを開始し、イベントを処理
3. `input_required` イベントを受信したら:
   a. ストリームの読み取りを終了
   b. metadata.message と metadata.preview をユーザーに表示
   c. 承認 / 中断ボタンを表示
4. ユーザーが選択したら:
   a. 承認 → message="yes" で再リクエスト
   b. 中断 → message="no" で再リクエスト (または何もしない)
5. 再リクエストの SSE ストリームを通常通り処理
```

### HTTP SSE 実装例 (Python)

```python
import json
import httpx

API_URL = "http://localhost:8101/test"


def send_message(session_id: str, message: str, stream: bool = True):
    """メッセージを送信し、SSE イベントを処理する."""
    payload = {"session_id": session_id, "message": message, "stream": stream}

    with httpx.Client(timeout=120) as client:
        with client.stream("POST", API_URL, json=payload) as response:
            response.raise_for_status()

            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[len("data: "):])

                if event["type"] == "input_required":
                    # ユーザーに確認を求める
                    metadata = event.get("metadata", {})
                    return {
                        "status": "input_required",
                        "message": metadata.get("message", ""),
                        "preview": metadata.get("preview", ""),
                    }

                if event["type"] == "token":
                    print(event.get("content", ""), end="", flush=True)

                if event["type"] == "done":
                    return {
                        "status": "done",
                        "message": event.get("message", ""),
                    }


# 使用例
session_id = "my-session"

# 1. 初回リクエスト
result = send_message(session_id, "こんにちは")

# 2. input_required が返ってきた場合
if result["status"] == "input_required":
    print(f"\n確認: {result['message']}")
    print(f"プレビュー: {result['preview']}")

    user_choice = input("承認しますか？ (yes/no): ")

    # 3. 再リクエスト (同じ session_id)
    result = send_message(session_id, user_choice)

print(f"\n最終回答: {result['message']}")
```

### HTTP SSE 実装例 (TypeScript)

```typescript
const API_URL = "http://localhost:8101/test";

interface StreamEvent {
  type: "node_start" | "node_end" | "token" | "input_required" | "done";
  node?: string;
  label?: string;
  content?: string;
  metadata?: { message: string; preview: string };
  session_id?: string;
  message?: string;
}

async function* streamEvents(
  sessionId: string,
  message: string
): AsyncGenerator<StreamEvent> {
  const response = await fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message, stream: true }),
  });

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      yield JSON.parse(line.slice(6)) as StreamEvent;
    }
  }
}

// 使用例
async function chat(sessionId: string, userMessage: string) {
  for await (const event of streamEvents(sessionId, userMessage)) {
    switch (event.type) {
      case "token":
        // トークンを UI に表示
        appendToUI(event.content ?? "");
        break;

      case "input_required":
        // 確認ダイアログを表示
        const approved = await showConfirmDialog({
          message: event.metadata?.message ?? "",
          preview: event.metadata?.preview ?? "",
        });

        // ユーザーの応答で再リクエスト (同じ session_id)
        await chat(sessionId, approved ? "yes" : "no");
        return;

      case "done":
        // 完了処理
        showFinalAnswer(event.message ?? "");
        break;
    }
  }
}
```

---

## 中断 (Abort) 時の挙動

ユーザーが中断を選択した場合:

- バックエンドは CONFIRM ノードで `aborted=True` をセットし、ワークフローを終了する
- `chat_history` に `"ユーザーにより中断されました。"` という AIMessage が追加される
- HTTP SSE では `done` イベントの `message` にこのテキストが入る
- A2A では `TaskArtifactUpdateEvent` にこのテキストが入る

フロントエンドは中断メッセージを通常の回答と同様に表示するか、
専用の UI (例: グレーアウトした通知) で表示するかを選択できる。
