# Sawagani

Sawagani は、Claude Agent SDK で動く軽量な**ハートビート駆動の自律エージェント**です。
一定間隔で自分から起動し、`tasks.md` を読んで作業を1つ実行します。やることが無ければ寝ます。

## 前提

- [uv](https://docs.astral.sh/uv/)
- `claude` CLI にログイン済み（Claude のサブスク認証を利用。API キー不要）

## セットアップ

```bash
uv sync
source .venv/bin/activate
sawagani init
```

## 使い方

```bash
sawagani tick                                  # 1回だけ実行（テスト用）
sawagani loop --interval 1800 --max-ticks 48   # 常駐ループ（30分間隔・最大48回）
```

仮想環境を activate しない場合は、`uv run sawagani init` のように実行できます。

## ファイルの役割

ユーザーが編集するのは、基本的に次の2つです。

- **`tasks.md`** … やること／見張る対象を書く作業リスト。空ならエージェントは何もしない。
- **`config.toml`** … 許可ツール、ループ間隔、Web 取得データの保存先などの動作設定。

Sawagani が管理するファイル／ディレクトリは次のとおりです。

- **`MEMORY.md`** … 実行ログ＝状態。Sawagani 本体が「いつ何をしたか」を追記する。
- **`web-data/`** … Web から取得したデータの保存先。`config.toml` で変更できる。
- **`STOP`** … ループ停止用のキルスイッチ。作成するとループが止まる（`touch STOP`）。

内部実装として `src/sawagani/settings.py` がありますが、これは `config.toml` を読むためのコードです。通常は編集しません。

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

[storage]
web_data_dir = "web-data"
```

- **Web 検索/取得**: `WebSearch`（探す）と `WebFetch`（ページ本文を取得）が既定で有効。
  論文やニュースを調べて本文や要点を `web_data_dir` 以下に保存できます。不要なら `allowed_tools` から外してください。
- **保存先制限**: `Write` / `Edit` / `MultiEdit` によるファイル変更は `web_data_dir` 以下だけ許可されます。
  `MEMORY.md` への追記は LLM ではなく Sawagani 本体が行います。

## セキュリティ

- 許可ツールは `config.toml` の `allowed_tools` で利用者が管理します（`permission_mode="dontAsk"` で許可外は自動拒否）。
  `Bash` や `Edit` など強い権限のツールも設定上は追加できるため、信頼できる環境・用途に合わせて最小限にしてください。
- ファイル変更は `web_data_dir` 以下に制限されます。`Bash` は保存先境界を保証できないため、設定に含めても実行時に拒否されます。
- 取得したウェブ本文は「データ」として扱い、ページ内の指示には従わない方針（プロンプトインジェクション対策）。
- 暴走防止: 1ティックのツール上限・総回数上限・間隔の下限・`STOP` キルスイッチ。
- `config.toml` に秘密情報は書かないこと（コミットされます。置く場合は gitignore する）。

## テスト

```bash
uv run pytest
uv run ty check
```
