# Claude Code LangGraph API

Claude Code CLI を LangGraph + FastAPI + A2A SDK でラップし、ストリーミング対応の API として公開するアプリケーションです。

---

## 目次

- [アーキテクチャ概要](#アーキテクチャ概要)
- [セットアップ](#セットアップ)
- [API エンドポイント](#api-エンドポイント)
- [ストリーミング](#ストリーミング)
- [A2A サーバー](#a2a-サーバー)
- [環境変数](#環境変数)
- [設定ファイル (app.yaml)](#設定ファイル-appyaml)
- [開発コマンド](#開発コマンド)

---

## アーキテクチャ概要

```
POST /claude-code (SSE) ──> FastAPI
                              │
                    LangGraph (ClaudeCodeWorkflow)
                              │
                    ┌─────────┴─────────┐
                    │  CLAUDE_CODE node  │  ← 単一ノード
                    └─────────┬─────────┘
                              │
                    claude -p "..." --output-format stream-json
                              │
                    adispatch_custom_event → astream_events → SSE / A2A
```

```
src/
├── main.py                          # FastAPI アプリ・エンドポイント定義
├── a2a_app/                         # A2A プロトコルサーバー
│   ├── server.py                    # A2A Starlette アプリのファクトリー
│   ├── executor.py                  # LangGraph を A2A で公開するエグゼキューター
│   ├── card.py                      # エージェントカード定義
│   └── client.py                    # A2A クライアント
├── application/
│   ├── states.py                    # LangGraph ステート定義
│   ├── stream.py                    # ストリーミング共通モジュール
│   ├── workflows/claude_code.py     # Claude Code 単一ノードワークフロー
│   └── nodes/claude_code.py         # Claude Code CLI 呼び出しノード
├── common/
│   ├── defs/types.py                # NodeName / ClientName 型定義
│   ├── di/                          # 依存性注入コンテナ・ビルダー
│   ├── schema/                      # Pydantic スキーマ
│   └── settings/app.py              # 環境変数ベースのアプリ設定
└── components/
    ├── llms/                        # LLM クライアントのモデル・ファクトリー
    └── io/                          # YAML・プロンプトローダー
```

### ワークフロー

```
START → CLAUDE_CODE → END
```

| ノード | 役割 |
|---|---|
| `CLAUDE_CODE` | Claude Code CLI を非対話実行し、stream-json 出力からトークンと進捗をリアルタイム配信 |

---

## セットアップ

### 前提条件

- Claude Code CLI がインストールされていること (`claude --version` で確認)
- `ANTHROPIC_API_KEY` が設定されている、または Bedrock / Vertex 認証が構成済みであること

### 起動

```bash
# Docker Compose で起動
docker compose up -d

# 開発サーバー起動 (ホットリロード)
make dev
```

---

## API エンドポイント

### GET /health

ヘルスチェック用。

```bash
curl http://localhost:8102/health
# => {"status": "ok"}
```

### POST /claude-code

Claude Code にユーザーメッセージを渡し、結果を返します。ファイル I/O は行わずメモリ上で完結します。

`session_id` は **有効な UUID (RFC 4122)** を指定する必要があります。省略時はサーバ側で新規発行し、レスポンスに含めて返します。

#### 非ストリーミング

```bash
curl -X POST http://localhost:8102/claude-code \
  -H "Content-Type: application/json" \
  -d '{"session_id": "550e8400-e29b-41d4-a716-446655440000", "message": "こんにちは！", "stream": false}'
```

レスポンス:

```json
{"session_id": "550e8400-e29b-41d4-a716-446655440000", "message": "こんにちは！何かお手伝いできることはありますか？"}
```

#### ストリーミング (SSE)

```bash
curl -X POST http://localhost:8102/claude-code \
  -H "Content-Type: application/json" \
  -d '{"session_id": "550e8400-e29b-41d4-a716-446655440003", "message": "こんにちは！", "stream": true}' \
  --no-buffer
```

---

## ストリーミング

`stream: true` を指定すると Server-Sent Events (SSE) 形式でリアルタイムにレスポンスを受け取れます。

### SSE イベント形式

各行は `data: <JSON>` の形式で送信されます。

| `type` | 追加フィールド | タイミング |
|---|---|---|
| `node_start` | `node`, `label` | ノードの実行開始時 |
| `node_end` | `node`, `label` | ノードの実行完了時 |
| `token` | `node`, `label`, `content` | Claude Code がテキストを生成するたび |
| `progress` | `node`, `label`, `content` | Claude Code のセッション開始時やツール実行時 |
| `done` | `session_id`, `message` | 完了時 (最終回答全文を含む) |

### 受信例

```
data: {"type":"node_start","node":"CLAUDE_CODE","label":"Claude Code 処理中"}
data: {"type":"progress","node":"CLAUDE_CODE","label":"Claude Code 処理中","content":"Claude Code セッション開始"}
data: {"type":"token","node":"CLAUDE_CODE","label":"Claude Code 処理中","content":"こんに"}
data: {"type":"token","node":"CLAUDE_CODE","label":"Claude Code 処理中","content":"ちは"}
data: {"type":"node_end","node":"CLAUDE_CODE","label":"Claude Code 処理中"}
data: {"type":"done","session_id":"550e8400-e29b-41d4-a716-446655440000","message":"こんにちは！..."}
```

---

## A2A サーバー

`/a2a` パスに A2A (Agent-to-Agent) プロトコルサーバーがマウントされています。

```bash
# エージェントカードの確認
curl http://localhost:8102/a2a/.well-known/agent.json
```

公開 URL は環境変数 `APP_A2A_BASE_URL` で設定します。

---

## 環境変数

### Claude Code 認証

Claude Code CLI の認証設定。いずれかを設定してください。

| 変数名 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API キー |
| `CLAUDE_CODE_USE_BEDROCK=1` + `AWS_REGION` | Amazon Bedrock 経由 |

### AWS Bedrock で利用する場合

Anthropic API キーの代わりに AWS Bedrock 経由で Claude を利用できます。

#### 1. 環境変数の設定

`.env` に以下を追加します。

```bash
# Bedrock を有効化
CLAUDE_CODE_USE_BEDROCK=1
AWS_REGION=us-east-1          # Bedrock が有効なリージョン
AWS_PROFILE=default           # AWS CLI プロファイル（IAM Role 利用時は不要）

# IAM ユーザーの場合（IAM Role / Instance Profile 利用時は不要）
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

> **注意:** `ANTHROPIC_API_KEY` が設定されているとそちらが優先されます。Bedrock を使う場合は `ANTHROPIC_API_KEY` を削除してください。

#### 2. docker-compose.yml への環境変数の追加

```yaml
services:
  claudecode:
    environment:
      - CLAUDE_CODE_USE_BEDROCK=${CLAUDE_CODE_USE_BEDROCK}
      - AWS_REGION=${AWS_REGION}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
```

> ECS / EC2 で IAM Role を利用する場合は `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` は不要です。

#### 3. IAM ポリシー

Bedrock を呼び出す IAM ユーザー / ロールには以下のポリシーが必要です。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "bedrock:InvokeModelWithResponseStream",
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
    }
  ]
}
```

#### 4. Bedrock モデルアクセスの有効化

AWS コンソール > Amazon Bedrock > Model access から、使用する Claude モデルへのアクセスをリクエスト・有効化してください。

---

### アプリケーション設定

`APP_` プレフィックスの環境変数でアプリ挙動を上書きできます。

| 環境変数 | デフォルト値 | 説明 |
|---|---|---|
| `APP_CONFIG_YAML_PATH` | `/app/config/app.yaml` | 設定 YAML のパス |
| `APP_PROMPTS_DIR` | `/app/prompts` | プロンプトテンプレートのディレクトリ |
| `APP_A2A_BASE_URL` | `http://host.docker.internal:8102/a2a/` | A2A エージェントカードの公開 URL |
| `APP_CLAUDE_CODE_CLI_PATH` | `claude` | Claude Code CLI の実行パス |
| `APP_CLAUDE_CODE_MAX_TURNS` | `0` | Claude Code CLI の最大ターン数 (0 以下で無制限) |
| `APP_CLAUDE_CODE_TIMEOUT` | `300` | Claude Code CLI のタイムアウト (秒) |
| `APP_CLAUDE_CODE_PERMISSION_MODE` | `auto` | ツール実行の権限モード (`default` / `acceptEdits` / `plan` / `bypassPermissions` / `dontAsk` / `auto`)。`bypassPermissions` は root 実行下で CLI 側にブロックされるため、コンテナ実行を考慮した既定として `auto` を採用 |
| `APP_LOG_LEVEL` | `INFO` | ログレベル |

### LLM プロバイダー (将来のノード拡張用)

| 変数名 | 説明 |
|---|---|
| `OPENAI_API_KEY` | OpenAI API キー |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI エンドポイント URL |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API キー |

---

## 設定ファイル (app.yaml)

`config/app.yaml` でチェックポイント設定を管理します。

```yaml
checkpoint:
  kind: sqlite
  dsn: "/app/db/sqlite/checkpoints.sqlite"
```

LLM クライアント定義 (`llms` セクション) は将来のノード拡張用に保持されています。

---

## 開発コマンド

```bash
make dev      # 開発サーバー起動 (ホットリロード, port 8102)
make lint     # ruff によるリントチェック
make format   # ruff によるフォーマット
make update   # 依存パッケージの再インストール
```


claude -p "明日の天気は？" --output-format stream-json --verbose --include-partial-messages

- ToDo
    - UI(Streamlit)と接続する.
    - `/tmp/claude/<session_id>/workspace` を作る. tmpの削除ポリシーを設定する.
    - Claude Code をそのディレクトリで起動する（書き込み範囲をそこに寄せる）
    - sandboxで、その workspace 以外を見えにくくする
    - S3へ保存・読み取る処理を追加する　※settings/app.pyで同期ON／OFFできるようにする.
    - 添付ファイルを受け付けられるようにする.
    - agent skillを用意して使えるようにする.
    - GPT DeepSearchを検討
    - 資料作成やデータ分析エージェントの開発を検討.
