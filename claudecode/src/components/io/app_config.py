from pathlib import Path

import yaml


def load_yaml(path: str | Path) -> dict:
    """YAML ファイルを読み込んで辞書として返す.

    Args:
        path: YAML ファイルのパス.

    Returns:
        YAML の内容を表す辞書.
    """
    with open(path) as f:
        return yaml.safe_load(f)
