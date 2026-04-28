はい。EC2 上で動かすなら、実運用しやすいのは次の 2 パターンです。

1. **Claude Code CLI を EC2 に入れて、Python から `subprocess` で呼ぶ**
2. **Python から Claude Agent SDK を直接使う**

公式には、Claude Code は Linux にネイティブインストールでき、CLI の非対話実行は `claude -p`、Python からのライブラリ利用は **Claude Agent SDK** が案内されています。なお、旧 “Claude Code SDK” は **Claude Agent SDK** に改名されています。 ([Claude API Docs][1])

---

## まず結論

* **「Claude Code そのものを EC2 で使いたい」**
  → **CLI を入れて `claude -p` を Python から叩く**のが一番わかりやすいです。 ([Claude API Docs][1])
* **「Python アプリの中に組み込みたい」**
  → **`pip install claude-agent-sdk`** を使うのが自然です。SDK は Claude Code と同じ基盤の agent loop と built-in tools を使えます。 ([Claude API Docs][2])
* **EC2 で AWS 認証に寄せたい**
  → Claude Code は **Amazon Bedrock** もサポートしていて、`CLAUDE_CODE_USE_BEDROCK=1` と `AWS_REGION` などで有効化できます。 ([Claude API Docs][1])

---

# パターンA: EC2 に Claude Code CLI を入れて Python から呼ぶ

## 1) 前提

Claude Code は Linux で動作し、Ubuntu 20.04+ / Debian 10+ などをサポートしています。Linux/macOS/WSL の推奨インストール方法は次です。 ([Claude API Docs][1])

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

インストール後の確認はこれです。 ([Claude API Docs][1])

```bash
claude --version
claude doctor
```

---

## 2) EC2 上のセットアップ例

Ubuntu 系を想定しています。

```bash
sudo apt-get update
sudo apt-get install -y curl git python3 python3-pip

# Claude Code をインストール
curl -fsSL https://claude.ai/install.sh | bash

# 確認
claude --version
claude doctor
```

Claude Code は起動後に認証が必要で、無料プランは Claude Code を含みません。Pro / Max / Team / Enterprise / Console アカウント、または Bedrock / Vertex / Foundry のような外部プロバイダ経由が必要です。 ([Claude API Docs][1])

---

## 3) 認証方法

### 方法A-1: Anthropic API キーを使う

スクリプト用途ではこれが単純です。`--bare` モードでは OAuth やキーチェーンを読まないため、**`ANTHROPIC_API_KEY`** または `apiKeyHelper` が必要です。 ([Claude][3])

```bash
export ANTHROPIC_API_KEY="YOUR_API_KEY"
```

### 方法A-2: Bedrock を使う

EC2 に IAM Role を付けるならこちらが自然です。Claude Code の Bedrock 利用では少なくとも次が必要です。 ([Claude][4])

```bash
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=us-east-1
```

公式には、Bedrock 利用時は `AWS_REGION` が必須で、`/login` `/logout` は使わず、認証は AWS 資格情報で行います。 ([Claude][4])

---

## 4) 非対話実行

Claude Code は `-p` で非対話実行できます。これは旧 “headless mode” に相当します。スクリプトや CI 用には `--bare` が推奨されています。 ([Claude][3])

```bash
claude --bare -p "Summarize this repository" --allowedTools "Read,Grep"
```

よく使うオプションはこれです。 ([Claude][3])

* `-p` / `--print`: 非対話実行
* `--bare`: ローカルの hooks / skills / CLAUDE.md / MCP 自動読込をスキップ
* `--allowedTools`: ツールを自動承認
* `--output-format json`: JSON 出力
* `--output-format stream-json`: ストリーミング JSON 出力

---

## 5) Python から CLI を呼ぶサンプル

### 最小版

```python
import json
import os
import subprocess

def run_claude(prompt: str, cwd: str = ".") -> dict:
    env = os.environ.copy()
    # APIキー運用なら事前に設定
    # env["ANTHROPIC_API_KEY"] = "YOUR_API_KEY"

    cmd = [
        "claude",
        "--bare",
        "-p", prompt,
        "--allowedTools", "Read,Grep",
        "--output-format", "json",
    ]

    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    return json.loads(result.stdout)

if __name__ == "__main__":
    out = run_claude("Summarize this project and list the main entry points.", cwd="/home/ubuntu/myrepo")
    print(out["result"])
```

Claude Code の `--output-format json` は、`result` フィールドにテキスト結果を返せます。 ([Claude][3])

---

### Bash / Edit まで許可してコード修正させる版

```python
import json
import subprocess

cmd = [
    "claude",
    "--bare",
    "-p", "Run the tests and fix any failures. Then explain what changed.",
    "--allowedTools", "Bash,Read,Edit",
    "--output-format", "json",
]

res = subprocess.run(cmd, cwd="/home/ubuntu/myrepo", capture_output=True, text=True, check=True)
data = json.loads(res.stdout)
print(data["result"])
```

公式にも、`Bash,Read,Edit` を許可してテスト実行と修正をさせる例があります。 ([Claude][3])

---

### ストリーミング版

```python
import json
import subprocess

cmd = [
    "claude",
    "--bare",
    "-p", "Summarize the repository",
    "--output-format", "stream-json",
    "--include-partial-messages",
]

with subprocess.Popen(
    cmd,
    cwd="/home/ubuntu/myrepo",
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
) as proc:
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        print(event)
```

CLI は `stream-json` を返せます。 ([Claude][3])

---

# パターンB: Python から Claude Agent SDK を直接使う

こちらは「Claude Code を Python ライブラリとして使う」イメージです。公式には、Agent SDK は Claude Code と同じ tools / agent loop / context management を使える Python / TypeScript SDK です。インストールは `pip install claude-agent-sdk`、認証は `ANTHROPIC_API_KEY` が基本です。 ([Claude API Docs][2])

## 1) インストール

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install claude-agent-sdk
```

([Claude API Docs][2])

---

## 2) 最小サンプル

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    options = ClaudeAgentOptions(
        cwd="/home/ubuntu/myrepo",
        allowed_tools=["Read", "Grep"],
        permission_mode="dontAsk",
    )

    async for message in query(
        prompt="Summarize this repository and list the important Python entry points.",
        options=options,
    ):
        print(message)

asyncio.run(main())
```

Agent SDK の概要と quickstart では、`query()` と `ClaudeAgentOptions` を使う形が案内されています。 ([Claude API Docs][2])

---

## 3) ファイル編集も含める実用版

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    options = ClaudeAgentOptions(
        cwd="/home/ubuntu/myrepo",
        allowed_tools=["Read", "Edit", "Bash", "Grep"],
        permission_mode="acceptEdits",
    )

    async for message in query(
        prompt=(
            "Run the test suite, fix failing tests, "
            "and then give me a concise changelog."
        ),
        options=options,
    ):
        print(message)

asyncio.run(main())
```

SDK では `allowed_tools` と `permission_mode` で権限制御できます。`acceptEdits` はファイル編集系を自動承認し、`dontAsk` は未許可ツールを即 deny するモードとして説明されています。 ([Claude][5])

---

## 4) ストリーミング出力

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import StreamEvent

async def main():
    options = ClaudeAgentOptions(
        cwd="/home/ubuntu/myrepo",
        allowed_tools=["Read", "Bash"],
        include_partial_messages=True,
    )

    async for message in query(
        prompt="List the important modules in this project and explain their roles.",
        options=options,
    ):
        if isinstance(message, StreamEvent):
            event = message.event
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    print(delta.get("text", ""), end="", flush=True)

asyncio.run(main())
```

`include_partial_messages=True` で部分出力を受け取れます。 ([Claude][6])

---

# パターンC: 「コード操作までは不要」で、単に Python から Claude を呼びたいだけなら

この場合は Claude Code ではなく、通常の **Anthropic Python SDK** のほうがシンプルです。公式 Python SDK は `Anthropic()` から `messages.create()` を呼ぶ形です。 ([Claude Platform][7])

```bash
pip install anthropic
export ANTHROPIC_API_KEY="YOUR_API_KEY"
```

```python
import anthropic

client = anthropic.Anthropic()

message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Hello, Claude. Summarize this deployment plan."}
    ],
)

print(message.content[0].text)
```

([Claude Platform][7])

---

# EC2 でのおすすめ構成

## いちばん簡単

* EC2 に Claude Code CLI を入れる
* `ANTHROPIC_API_KEY` を環境変数で渡す
* Python から `subprocess + claude --bare -p ... --output-format json`

## AWS に寄せる

* EC2 に IAM Role を付与
* Claude Code を Bedrock モードで使う
* `CLAUDE_CODE_USE_BEDROCK=1`
* `AWS_REGION=...`

Claude Code は Bedrock を公式サポートしています。 ([Claude API Docs][1])

---

# ハマりやすい点

* **`--bare` を付けないと**、そのマシンの `~/.claude` やプロジェクトの設定を読み込んで挙動が変わることがあります。スクリプト用途では `--bare` が推奨です。 ([Claude][3])
* **`allowedTools` / `allowed_tools` は “利用可能化” ではなく “自動承認”** です。未指定ツールが完全に消えるわけではなく、permission mode に従って扱われます。 ([Claude][5])
* **旧 SDK 名の情報に注意**。現在は **Claude Agent SDK** 名称です。 ([Claude API Docs][2])

---

# 迷ったらこの構成で始めればOK

## まず EC2 に入れる

```bash
sudo apt-get update
sudo apt-get install -y curl git python3 python3-pip
curl -fsSL https://claude.ai/install.sh | bash
claude --version
```

## API キーを設定

```bash
export ANTHROPIC_API_KEY="YOUR_API_KEY"
```

## Python から呼ぶ

```python
import json
import subprocess

res = subprocess.run(
    [
        "claude",
        "--bare",
        "-p", "Summarize this repository.",
        "--allowedTools", "Read,Grep",
        "--output-format", "json",
    ],
    cwd="/home/ubuntu/myrepo",
    capture_output=True,
    text=True,
    check=True,
)

print(json.loads(res.stdout)["result"])
```

必要なら次に、**Bedrock版の環境変数付きセットアップ例** と **systemd / Docker / FastAPI から呼ぶ実装例** までまとめます。

[1]: https://docs.anthropic.com/en/docs/claude-code/setup "Advanced setup - Claude Code Docs"
[2]: https://docs.anthropic.com/en/docs/claude-code/sdk "Agent SDK overview - Claude Code Docs"
[3]: https://code.claude.com/docs/en/headless "Run Claude Code programmatically - Claude Code Docs"
[4]: https://code.claude.com/docs/en/amazon-bedrock "Claude Code on Amazon Bedrock - Claude Code Docs"
[5]: https://code.claude.com/docs/en/agent-sdk/permissions "Configure permissions - Claude Code Docs"
[6]: https://code.claude.com/docs/en/agent-sdk/streaming-output "Stream responses in real-time - Claude Code Docs"
[7]: https://platform.claude.com/docs/en/api/sdks/python?utm_source=chatgpt.com "Python SDK - Claude API Docs"


---

パターンC: 「コード操作までは不要」で、単に Python から Claude を呼びたいだけなら
の場合って、単純にLLMに投げて生成結果が返ってくるよ、と言う意味ですよね？

今回は、ClaudeCodeのエージェンティックなコーディング／ライティングを使いたい（特にライティング）というのが目的です。
例えば、PR文生成、企画書・設計書作成　などで使えると思っています。

これをAPIで実装したいのですが、どういうアプローチがありますか？
リクエストが来たらtempファイルを用意してそれを編集させて結果を返すとか？ほかには？


---


はい、その理解で合っています。
**パターンC** は「通常の LLM API を Python から呼んで、入力テキストに対する生成結果を返す」方式です。Claude Code 的な **ツール実行・ファイル読取/編集・反復的な agent loop** は自前実装になります。一方で **Claude Code / Agent SDK** は、同じツール実行・agent loop・コンテキスト管理を含んだ形でプログラムから使えます。 ([Claude API Docs][1])

今回の目的が

* PR 文生成
* 企画書・設計書作成
* 既存 repo や既存ドキュメントを読んだうえでのライティング

なら、**素の LLM API より Claude Code 系の agent を裏で動かす設計**のほうがかなり噛み合います。([Claude API Docs][1])

---

## まず結論

API として実装するアプローチは、実務上はこの3つです。

### 1. 一時ワークスペースを作って Agent SDK / CLI に編集させる

一番おすすめです。
リクエストごとに `/tmp/job-xxxxx/` のような **隔離ディレクトリ** を作り、そこに入力材料を置いて、Claude Code にその中だけを読ませて書かせます。終わったら生成物を回収して返します。

向いている用途:

* PR 文生成
* 設計書生成
* 企画書ドラフト生成
* changelog / release note 生成
* 既存 markdown の改稿

---

### 2. Git 作業ツリー / リポジトリ複製に対して agent を動かす

「repo を見て PR 文を書く」「差分から設計メモを書く」ならこれです。
対象 repo を shallow clone するか worktree を切って、その中で Claude Code を動かします。

向いている用途:

* Git diff から PR description 作成
* コードベースを読んだ設計書生成
* Issue → implementation plan 作成

---

### 3. “文書編集専用” の仮想プロジェクトを毎回構成する

コード repo ではなく、**documents-first** のやり方です。
例えば毎回こんな構成を作ります。

```text
/job-1234
  /inputs
    request.md
    context.md
    product_requirements.md
    meeting_notes.md
  /outputs
    draft.md
  CLAUDE.md
```

そのうえで「`outputs/draft.md` を作成・編集せよ」と指示します。
ライティング主体ならかなり扱いやすいです。

---

# いちばん自然な設計

あなたのケースでは、**“ジョブごとの一時ワークスペース + Agent SDK”** が本命です。

理由は、Agent SDK は Claude Code と同じ **tool execution / agent loop / context management** を持ち、CLI より Python から制御しやすいからです。CLI でもできますが、API サーバの裏側なら SDK のほうが扱いやすいです。 ([Claude API Docs][1])

---

# 推奨アーキテクチャ

## A. 非同期ジョブ型 API

たとえば:

* `POST /jobs`
* `GET /jobs/{id}`
* `GET /jobs/{id}/result`

この形が安定です。
PR 文や設計書生成は数秒〜数十秒かかることがあり、Agent は複数ステップ動くので、同期 HTTP 1 発よりジョブ型が向いています。

---

## B. ジョブごとに隔離ディレクトリを作る

例:

```text
/tmp/claude-jobs/{job_id}/
  inputs/
  outputs/
  metadata.json
  CLAUDE.md
```

ここに:

* ユーザー入力
* 参照させたい差分やファイル
* 生成先ファイル
* 実行ルール

を置きます。

---

## C. ツール権限を絞る

ライティング用途では、最初はかなり絞ってよいです。
Claude Code / Agent SDK では、`allowed_tools` と `permissionMode` を組み合わせられ、**ロックダウンしたいなら `dontAsk` と限定ツールの組み合わせ**が推奨されています。 ([Claude][2])

たとえば:

* `Read`
* `Grep`
* `Edit`
* 必要なら `Write`

くらいから始めるのが安全です。
`Bash` は本当に必要なときだけでよいです。

---

# 実装アプローチ別の比較

## アプローチ1: tempファイルを作って編集させる

あなたが書いてくれた案です。**かなり良いです**。

### どうやるか

* `request.md` に依頼を書く
* `context/` に補足資料を置く
* `outputs/result.md` を生成対象にする
* agent に「資料を読んで result.md を完成させて」と指示

### 長所

* 実装が簡単
* 出力がファイルとして残る
* 途中成果物も拾いやすい
* ライティング用途に強い

### 短所

* repo 全体理解が必要なケースでは入力材料の準備が少し面倒

### 典型例

* 企画書下書き
* 設計書ドラフト
* 会議メモから提案書作成

---

## アプローチ2: テンポラリ Git repo / worktree を作る

PR 文生成ならこちらが強いです。

### どうやるか

* 対象 repo を clone または worktree
* `git diff`, `git log`, 関連ファイルを agent に読ませる
* `outputs/pr.md` を生成させる

### 長所

* 差分や文脈を拾いやすい
* PR / release note と相性がいい
* 「変更意図」まで書かせやすい

### 短所

* clone コストがある
* セキュリティと権限設計が必要

### 典型例

* PR title / body 生成
* change summary 生成
* migration guide 生成

---

## アプローチ3: すべてメモリ上で渡して最終文だけ返す

これは **Claude Code っぽさをあまり使わない** です。
単に prompt に全部埋め込んで最終出力だけもらう方式。

### 長所

* 実装が最も単純
* temp ファイル不要

### 短所

* agent 的な「読んで、整理して、ファイルを育てる」感じが弱い
* 長文資料や段階的推敲に弱い

これは今回の主目的にはやや不向きです。

---

## アプローチ4: “書式テンプレート + 入力資料 + 編集対象ファイル” のハイブリッド

個人的にはこれが最も実用的です。

### 例

```text
/job-1234
  templates/
    pr_template.md
    design_doc_template.md
  inputs/
    diff.txt
    issue.md
    context.md
  outputs/
    result.md
  CLAUDE.md
```

### agent への指示

* まず inputs を読む
* template を元に outputs/result.md を埋める
* 曖昧な点は assumptions として明記
* 過剰な推測はしない

### 長所

* 出力品質が安定
* フォーマットを固定しやすい
* API 化しやすい

これは PR 文、設計書、企画書どれにも使えます。

---

# かなりおすすめの実務パターン

## パターンA: PR 文生成 API

### 入力

* repo path or repo archive
* base branch / head branch
* issue summary
* optional audience

### ワークスペース

```text
inputs/
  diff.patch
  changed_files.txt
  issue.md
outputs/
  pr.md
```

### agent 指示

```text
Read the diff and issue summary, then write outputs/pr.md.
Include:
- Summary
- Why
- What changed
- Risks / impact
- Test plan

Be concise and concrete. Do not invent behavior not supported by the diff.
```

この用途は Claude Code の common workflows にも近く、PR 作成やコードベース理解は公式の主要ユースケースに入っています。 ([Claude API Docs][3])

---

## パターンB: 設計書生成 API

### 入力

* feature request
* existing docs
* code snippets
* constraints

### ワークスペース

```text
inputs/
  feature_request.md
  constraints.md
  existing_architecture.md
  code_context/
outputs/
  design_doc.md
templates/
  design_doc_template.md
```

### agent 指示

```text
Create outputs/design_doc.md based on templates/design_doc_template.md.
Read all files under inputs first.
Where information is missing, add an "Open Questions" section instead of guessing.
```

---

## パターンC: 企画書ドラフト API

### 入力

* 背景
* ターゲット
* KPI
* 会議メモ
* 参考資料

### ワークスペース

```text
inputs/
  brief.md
  meeting_notes.md
  kpi.md
templates/
  proposal_template.md
outputs/
  proposal.md
```

### agent 指示

```text
Draft a proposal in outputs/proposal.md.
Use a professional Japanese business tone.
Prefer structure, brevity, and explicit assumptions.
```

ライティング中心なら、この documents-first 構成がかなり強いです。

---

# Agent SDK での実装イメージ

ライティング用途なら、最初は `Read`, `Grep`, `Edit` くらいで十分です。
Agent SDK は Python から使え、ツールと permission mode を設定できます。 ([Claude API Docs][1])

```python
import asyncio
import os
import tempfile
from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions

PROMPT = """
Read all files in inputs/.
Then create outputs/result.md.

Requirements:
- Follow templates/design_doc_template.md if present.
- Do not invent facts not supported by the input files.
- If something is unclear, add an 'Open Questions' section.
- Write in Japanese.
"""

async def run_job(input_files: dict[str, str]) -> str:
    with tempfile.TemporaryDirectory(prefix="claude-job-") as tmp:
        root = Path(tmp)
        (root / "inputs").mkdir()
        (root / "outputs").mkdir()
        (root / "templates").mkdir()

        for rel_path, content in input_files.items():
            path = root / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        options = ClaudeAgentOptions(
            cwd=str(root),
            allowed_tools=["Read", "Grep", "Edit"],
            permission_mode="dontAsk",
        )

        async for _ in query(prompt=PROMPT, options=options):
            pass

        return (root / "outputs" / "result.md").read_text(encoding="utf-8")

# asyncio.run(run_job({...}))
```

ポイントは、

* **ジョブごとに隔離**
* **生成対象ファイルを明示**
* **推測禁止 / open questions 明示**
* **permission を最小化**

です。
`allowed_tools` と `dontAsk` の組み合わせは、許可したもの以外を明確に deny したいケースに向いています。 ([Claude][2])

---

# CLI で API の裏側を組む方法もある

SDK ではなく CLI の `claude -p` を API サーバから呼ぶ方法もあります。
Claude Code は `-p` で非対話実行でき、`--bare` はスクリプト用途の推奨モードです。JSON 出力もできます。 ([Claude][4])

たとえば:

```python
import json
import subprocess
import tempfile
from pathlib import Path

def run_claude_cli(input_text: str) -> str:
    with tempfile.TemporaryDirectory(prefix="claude-job-") as tmp:
        root = Path(tmp)
        (root / "inputs").mkdir()
        (root / "outputs").mkdir()

        (root / "inputs" / "brief.md").write_text(input_text, encoding="utf-8")
        (root / "outputs" / "result.md").write_text("", encoding="utf-8")

        prompt = """
Read inputs/brief.md and write outputs/result.md.
Write in Japanese.
Do not invent facts.
"""

        cmd = [
            "claude",
            "--bare",
            "-p", prompt,
            "--allowedTools", "Read,Edit,Grep",
            "--output-format", "json",
        ]

        subprocess.run(cmd, cwd=root, check=True, capture_output=True, text=True)
        return (root / "outputs" / "result.md").read_text(encoding="utf-8")
```

CLI の利点はシンプルさ、SDK の利点は Python 側制御のしやすさです。

---

# ほかにあるアプローチ

## 1. “Plan only” → “Write” の2段階

まず plan mode 的に構成案だけ作らせ、そのあと書かせる方法です。
Claude Code には `plan` permission mode があり、このモードではファイル変更やコマンド実行をしません。 ([Claude][5])

使い分けると:

* Step 1: 構成案 / アウトライン作成
* Step 2: result.md に本文生成

長文の設計書で品質が安定しやすいです。

---

## 2. Hook で後処理する

Claude Code には hooks があり、編集後やタスク完了時にコマンドを実行できます。書式整形や検証を自動化できます。 ([Claude API Docs][6])

ライティングなら:

* markdown lint
* frontmatter 付与
* テンプレチェック
* 禁止表現チェック

などを後段で自動実行できます。

---

## 3. 会話継続型セッションを持つ

CLI には `--continue` があり、継続会話が可能です。反復レビュー型の文書編集なら使えます。 ([Claude][7])

ただ、API で運用するなら最初は **毎回 stateless job** のほうが簡単です。
状態管理を入れるのは第2段階でよいです。

---

# 実務上のおすすめ順

## 最初に作るべきもの

**documents-first の一時ワークスペース方式**

理由:

* ライティング用途に最適
* セキュア
* デバッグしやすい
* 生成結果がファイルで残る
* 失敗時の再現が容易

---

## 次に追加すると良いもの

* テンプレート管理
* Git diff 取り込み
* アウトライン→本文の2段階生成
* Hook で markdown lint
* ジョブ履歴保存

---

# こう考えると整理しやすいです

今回やりたいのは「LLM に文章を聞く」ではなく、
**“限定された作業ディレクトリの中で、資料を読み、必要ならファイルを編集し、成果物を完成させるエージェント”** を API の裏に置くことです。

その意味では、設計の中心は

* **プロンプト**
* **作業ディレクトリ構成**
* **許可ツール**
* **成果物ファイルの場所**
* **再現性**
  です。

---

# ひとまずのおすすめ構成

* 実行基盤: EC2
* 実装: FastAPI + Claude Agent SDK
* 実行単位: 1リクエスト = 1一時ディレクトリ
* ツール: `Read`, `Grep`, `Edit`
* permission: `dontAsk`
* 入力: `inputs/`
* 出力: `outputs/result.md`
* テンプレ: `templates/*.md`
* 必要に応じて repo / diff を `inputs/` に配置

これが最初の一歩としてかなり良いです。
その後、PR 生成だけ repo worktree 型に広げるのが自然です。

次に進めるなら、**FastAPI で `/generate-pr` と `/generate-design-doc` を持つ最小 API サンプル** をそのまま書けます。

[1]: https://docs.anthropic.com/en/docs/claude-code/sdk?utm_source=chatgpt.com "Agent SDK overview - Claude Code Docs"
[2]: https://code.claude.com/docs/en/agent-sdk/permissions?utm_source=chatgpt.com "Configure permissions - Claude Code Docs"
[3]: https://docs.anthropic.com/en/docs/claude-code/common-workflows?utm_source=chatgpt.com "Common workflows - Claude Code Docs"
[4]: https://code.claude.com/docs/ja/headless?utm_source=chatgpt.com "Claude Code をプログラムで実行する"
[5]: https://code.claude.com/docs/ja/permissions?utm_source=chatgpt.com "権限を設定する - Claude Code Docs"
[6]: https://docs.anthropic.com/en/docs/claude-code/hooks-guide?utm_source=chatgpt.com "Automate workflows with hooks - Claude Code Docs"
[7]: https://code.claude.com/docs/id/headless?utm_source=chatgpt.com "Jalankan Claude Code secara programatis"


---

