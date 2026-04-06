import logging as base_logging


def getLogger(name: str) -> base_logging.Logger:  # noqa: N802
    """ロガーを生成して返す.

    Args:
        name: ロガー名 (通常は __name__ を渡す).

    Returns:
        設定済みの Logger インスタンス.
    """
    base_logging.basicConfig(
        level=base_logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s:%(funcName)s - %(message)s"
    )
    return base_logging.getLogger(name)
