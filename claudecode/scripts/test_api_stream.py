"""HTTP SSE ストリーミングの手動テストスクリプト.

Claude Code エンドポイントの E2E 動作確認用。
"""

from __future__ import annotations

import json
import sys

import httpx

BASE_URL = "http://localhost:8102"
DEFAULT_SESSION_ID = "test-api"


def send(session_id: str, message: str) -> None:
    """メッセージを送信し SSE イベントを表示する."""
    payload = {"session_id": session_id, "message": message, "stream": True}
    print(f"\n>>> POST /claude-code  message={message!r}")
    print("-" * 60)

    with httpx.Client(timeout=120) as client:
        with client.stream("POST", BASE_URL + "/claude-code", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[len("data: "):])
                etype = event.get("type", "")
                print(f"  [{etype:17s}] ", end="")

                if etype == "node_start":
                    print(f"node={event.get('node')}  label={event.get('label')}")
                elif etype == "node_end":
                    print(f"node={event.get('node')}")
                elif etype == "token":
                    content = event.get("content", "")
                    preview = content[:80] + ("..." if len(content) > 80 else "")
                    print(f"node={event.get('node')}  content={preview!r}")
                elif etype == "progress":
                    print(f"node={event.get('node')}  content={event.get('content', '')!r}")
                elif etype == "done":
                    msg = event.get("message", "")
                    preview = msg[:120] + ("..." if len(msg) > 120 else "")
                    print(f"message={preview!r}")
                else:
                    print(json.dumps(event, ensure_ascii=False))


def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SESSION_ID
    message = sys.argv[2] if len(sys.argv) > 2 else "テスト用メッセージです"

    print(f"=== API SSE テスト (session_id={session_id!r}) ===")
    send(session_id, message)
    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
