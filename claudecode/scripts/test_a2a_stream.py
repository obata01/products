"""A2A ストリーミングの手動テストスクリプト.

Claude Code エンドポイントの E2E 動作確認用。
"""

from __future__ import annotations

import asyncio
import json
import sys

from a2a.types import (
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
)

from src.a2a_app.client import AgentClient, text_from_artifact, text_from_message

A2A_BASE_URL = "http://localhost:8102/a2a"


async def send(client: AgentClient, message: str) -> None:
    """メッセージを送信しイベントを表示する."""
    print(f"\n>>> A2A send  message={message!r}")
    print("-" * 60)

    async for event in client.stream_events(message):
        match event:
            case (Task(), TaskStatusUpdateEvent() as ev):
                state = ev.status.state

                if state == TaskState.working and ev.status.message:
                    text = text_from_message(ev.status.message)
                    try:
                        parsed = json.loads(text)
                        etype = parsed.get("type", "")
                        print(f"  [working/{etype:13s}] ", end="")
                        if etype == "token":
                            content = parsed.get("content", "")
                            preview = content[:80] + ("..." if len(content) > 80 else "")
                            print(f"node={parsed.get('node')}  content={preview!r}")
                        elif etype in ("node_start", "node_end"):
                            print(f"node={parsed.get('node')}  label={parsed.get('label')}")
                        elif etype == "progress":
                            print(f"node={parsed.get('node')}  content={parsed.get('content', '')!r}")
                        else:
                            print(text[:100])
                    except json.JSONDecodeError:
                        print(f"  [working           ] {text[:100]}")

                elif state == TaskState.completed:
                    print(f"  [completed         ] final={ev.final}")

                else:
                    print(f"  [{str(state):20s}] final={ev.final}")

            case (_, TaskArtifactUpdateEvent() as ev):
                text = text_from_artifact(ev.artifact)
                preview = text[:120] + ("..." if len(text) > 120 else "")
                print(f"  [artifact          ] {preview!r}")

            case Message() as msg:
                text = text_from_message(msg)
                preview = text[:120] + ("..." if len(text) > 120 else "")
                print(f"  [message           ] {preview!r}")

            case _:
                print(f"  [unknown           ] {type(event).__name__}")


async def main() -> None:
    message = sys.argv[1] if len(sys.argv) > 1 else "テスト用メッセージです"

    print("=== A2A ストリーミングテスト ===")

    async with AgentClient(A2A_BASE_URL) as client:
        await send(client, message)
        print("\n=== 完了 ===")


if __name__ == "__main__":
    asyncio.run(main())
