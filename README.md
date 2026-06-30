# Sawagani

Sawagani は、Claude Agent SDK で動く軽量な**ハートビート駆動の自律エージェント**です。
一定間隔で自分から起動し、`tasks.md` を読んで作業を1つ実行します。やることが無ければ寝ます。

## 前提

- [uv](https://docs.astral.sh/uv/)
- `claude` CLI にログイン済み（Claude のサブスク認証を利用。API キー不要）

## セットアップ

```bash
uv sync
```

## 使い方

```bash
uv run sawagani tick                                  # 1回だけ実行（テスト用）
uv run sawagani loop --interval 1800 --max-ticks 48   # 常駐ループ（30分間隔・最大48回）
```

- **`tasks.md`** … やること／見張る対象を書く（ユーザーが編集）。空ならエージェントは何もしない。
- **`MEMORY.md`** … 実行ログ＝状態。エージェントが「いつ何をしたか」を追記する。
- **停止** … プロジェクト直下に `STOP` ファイルを作るとループが止まる（`touch STOP`）。

状態ファイル（`tasks.md` / `MEMORY.md` / `STOP`）は実行ディレクトリ基準です。
別の場所で動かす場合は `SAWAGANI_HOME` でデータディレクトリを指定できます。

## セキュリティ

- 許可ツールは `Read` / `Write` のみ（`permission_mode="dontAsk"` で許可外は自動拒否）
- 暴走防止: 1ティックのツール上限・総回数上限・間隔の下限・`STOP` キルスイッチ

## テスト

```bash
uv run pytest
```
