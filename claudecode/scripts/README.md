# テストスクリプト

開発者がローカル環境で API / A2A の動作確認を行うためのスクリプト。

## 前提

サーバーが起動していること。

```bash
make dev
```

## HTTP SSE テスト

```bash
# 基本 (デフォルト session_id + メッセージ)
python scripts/test_api_stream.py

# session_id とメッセージを指定
python scripts/test_api_stream.py my-session "こんにちは"
```

CONFIRM ノードで `input_required` が返されると対話プロンプトが表示される。
承認ワード (`yes`, `ok`, `はい` 等) を入力すると resume し、それ以外は中断する。

## A2A テスト

```bash
# 基本
python scripts/test_a2a_stream.py

# メッセージを指定
python scripts/test_a2a_stream.py "こんにちは"
```

A2A は `context_id` でセッションを管理するため、`session_id` の指定は不要。
