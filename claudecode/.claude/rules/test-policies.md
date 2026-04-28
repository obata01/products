---
inclusion: fileMatch
fileMatchPattern: "tests/**"
---

## テストコード方針

- テストフレームワークは pytest を使用する.
- 極力 `pytest.mark.parametrize` でテストケースを共通化し、テストコード自体の保守性を高めること.
- テストコードは `tests/` ディレクトリに配置する（`src/` 内には置かない）.
- テストファイル名は `test_<対象モジュール名>.py` とする.
