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

状態ファイル（`tasks.md` / `MEMORY.md` / `STOP` / `config.toml`）は実行ディレクトリ基準です。
別の場所で動かす場合は `SAWAGANI_HOME` でデータディレクトリを指定できます。

## 設定（`config.toml`）

許可ツールや動作パラメータは、コード（`src`）を触らず `config.toml` で変更できます。
ファイルが無ければ組み込みのデフォルトで動作します。

```toml
[agent]
allowed_tools = ["Read", "Write", "WebSearch", "WebFetch"]  # ここから減らせば権限を絞れる
max_turns_per_tick = 12

[loop]
default_interval_sec = 1800
min_interval_sec = 60
default_max_ticks = 48
```

- **Web 検索/取得**: `WebSearch`（探す）と `WebFetch`（ページ本文を取得）が既定で有効。
  論文やニュースを調べて要点を `MEMORY.md` に記録できます。不要なら `allowed_tools` から外してください。

## セキュリティ

- 許可ツールは `config.toml` の `allowed_tools` で利用者が管理します（`permission_mode="dontAsk"` で許可外は自動拒否）。
  `Bash` や `Edit` など強い権限のツールも設定上は追加できるため、信頼できる環境・用途に合わせて最小限にしてください。
- 取得したウェブ本文は「データ」として扱い、ページ内の指示には従わない方針（プロンプトインジェクション対策）。
- 暴走防止: 1ティックのツール上限・総回数上限・間隔の下限・`STOP` キルスイッチ。
- `config.toml` に秘密情報は書かないこと（コミットされます。置く場合は gitignore する）。

## テスト

```bash
uv run pytest
uv run ty check
```
