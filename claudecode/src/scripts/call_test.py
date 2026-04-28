"""POST /test エンドポイントを呼び出すスクリプト."""

import argparse
import json
import uuid

import httpx

from src.common.lib.logging import getLogger

logger = getLogger(__name__)


def _build_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="POST /test エンドポイントを呼び出す")
    parser.add_argument(
        "-m",
        "--message",
        required=True,
        help="送信するメッセージ",
    )
    parser.add_argument(
        "-s",
        "--session-id",
        default=None,
        help="セッション ID (省略時は UUID を自動生成)",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8102",
        help="サーバーのベース URL (デフォルト: http://localhost:8102)",
    )
    return parser.parse_args()


def main() -> None:
    """コマンドライン引数を解析して POST /test エンドポイントを呼び出す."""
    args = _build_parser()

    session_id = args.session_id or str(uuid.uuid4())
    payload = {"session_id": session_id, "message": args.message}

    logger.info("Sending request to %s/test", args.url)
    logger.info("Payload: %s", json.dumps(payload, ensure_ascii=False, indent=2))

    response = httpx.post(f"{args.url}/test", json=payload)
    response.raise_for_status()

    data = response.json()
    logger.info("Session ID : %s", data["session_id"])
    logger.info("Response   : %s", data["message"])


if __name__ == "__main__":
    main()
