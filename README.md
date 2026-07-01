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
sawagani start   # バックグラウンドでハートビート開始
sawagani status  # 実行状態とログの場所を表示
sawagani stop    # バックグラウンド実行を停止
```

動作確認やデバッグでは、前面実行もできます。

```bash
sawagani tick                                  # 1回だけ実行（テスト用）
sawagani loop --interval 1800 --max-ticks 48   # 前面で常駐ループ（30分間隔・最大48回）
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
- **`sawagani.pid`** … バックグラウンド実行中のプロセスID。
- **`sawagani.log`** … バックグラウンド実行の標準出力・標準エラー。

内部実装として `src/sawagani/settings.py` がありますが、これは `config.toml` を読むためのコードです。通常は編集しません。

状態ファイル（`tasks.md` / `MEMORY.md` / `STOP` / `config.toml`）は実行ディレクトリ基準です。
別の場所で動かす場合は `SAWAGANI_HOME` でデータディレクトリを指定できます。

## 設定（`config.toml`）

許可ツールや動作パラメータは、コード（`src`）を触らず `config.toml` で変更できます。
`sawagani init` はローカル用の `config.toml` を作成します。リポジトリでは安全な例として
`config.example.toml` だけを管理し、ID などを含む `config.toml` は git 管理しません。
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

[downloads]
allow_bash_downloads = false
allowed_commands = ["curl", "wget"]

[discord]
enabled = false
conversation = false
# guild_id = 123456789012345678
# channel_id = 123456789012345678
# allowed_user_ids = [123456789012345678]
```

- **Web 検索/取得**: `WebSearch`（探す）と `WebFetch`（ページ本文を取得）が既定で有効。
  論文やニュースを調べて本文や要点を `web_data_dir` 以下に保存できます。不要なら `allowed_tools` から外してください。
- **保存先制限**: `Write` / `Edit` / `MultiEdit` によるファイル変更は `web_data_dir` 以下だけ許可されます。
  `MEMORY.md` への追記は LLM ではなく Sawagani 本体が行います。
- **画像/PDFなどのダウンロード**: `[downloads] allow_bash_downloads = true` にすると、LLM が `curl` / `wget` を Bash で使えるようになります。
  個人利用向けの緩い許可なので、取得物は自己責任で扱い、保存先は原則 `web_data_dir` 以下にしてください。

## セキュリティ

- 許可ツールは `config.toml` の `allowed_tools` で利用者が管理します（`permission_mode="dontAsk"` で許可外は自動拒否）。
  `Bash` や `Edit` など強い権限のツールも設定上は追加できるため、信頼できる環境・用途に合わせて最小限にしてください。
- ファイル変更は `web_data_dir` 以下に制限されます。`Bash` は保存先境界を保証できないため原則拒否されますが、`[downloads] allow_bash_downloads = true` の場合だけ `curl` / `wget` を許可できます。
- 取得したウェブ本文は「データ」として扱い、ページ内の指示には従わない方針（プロンプトインジェクション対策）。
- 暴走防止: 1ティックのツール上限・総回数上限・間隔の下限・`STOP` キルスイッチ。
- `config.toml` はローカル運用ファイルとして `.gitignore` しています。Bot Token などの秘密情報は引き続き書かず、環境変数で渡してください。

## Discord

Discord から Sawagani に指示を出す場合は Discord Bot を使います。Webhook は通知向けで、Discord 側からの指示受け取りには使いません。

Sawagani は slash command（`/sawagani ...`）で操作します。slash command は Discord の Application Command 機能のため、Bot をサーバーへ招待する際に **`applications.commands` スコープでの認可が必須**です（トークンだけでは登録できず、`tree.sync()` が `403 Missing Access` になります）。

### 1. Bot を作成する

1. [Discord Developer Portal](https://discord.com/developers/applications) で New Application → アプリを作成。
2. **Bot** タブで Bot を作成し、**Reset Token** でトークンを取得（手順5で使う）。
3. **Bot** タブの Privileged Gateway Intents は**すべて OFF のままでよい**（Sawagani はメッセージ本文を読まないため）。
   - 起動ログに `Privileged message content intent is missing` という警告が出ますが、slash command だけを使う構成では無害です。

### 2. Bot をサーバーに招待する（`applications.commands` 認可が必須）

1. **OAuth2 → URL Generator** を開く。
2. **Scopes** で次の2つに**両方**チェック：
   - ✅ `bot`
   - ✅ `applications.commands`（これが無いと slash command を登録できない）
3. **Bot Permissions** で最小限にチェック：
   - ✅ View Channels (チャンネルを表示)
   - ✅ Send Messages (メッセージを送る)
4. 生成された URL をブラウザで開き、対象サーバーを選択して**「認可」ボタンを押し切る**。
   - Bot が既にサーバーにいても、この手順で `applications.commands` スコープを追加できます（Kick 不要）。
   - 認可済みかは「サーバー設定 → 連携サービス（Integrations）」に Bot が表示されるかで確認できます。

### 3. ID を調べる

Discord の「設定 → 詳細設定 → 開発者モード」を ON にすると、サーバー / チャンネル / ユーザーを右クリックして「IDをコピー」できます。

### 4. `config.toml` の `[discord]` を設定する

```toml
[discord]
enabled = true                          # 必須。false だと起動時に停止する
guild_id = 123456789012345678           # 必須。本物のサーバーIDに置き換える
channel_id = 123456789012345678         # 任意。特定チャンネルに絞らないなら行ごと削除
allowed_user_ids = [123456789012345678] # 任意。利用者を絞らないなら行ごと削除
```

- `guild_id` は slash command の同期先になるため、**プレースホルダーの例の値のままだと `403 Missing Access` になります**。必ず実際のサーバーIDに置き換えてください。
- `channel_id` / `allowed_user_ids` は省略可。指定するとそのチャンネル・ユーザーに実行を制限します。
- ⚠️ Bot Token は**環境変数で渡し、`config.toml` には書かないこと**。

### 5. 起動する

```bash
export SAWAGANI_DISCORD_BOT_TOKEN="..."   # 手順1で取得したトークン
sawagani discord start
```

使える slash command:

```text
/sawagani status
/sawagani task <内容>
/sawagani tick
```

`/sawagani task` は直接実行せず、まず `tasks.md` に追記します。次の tick で通常の権限境界の中で処理されます。

### 会話モード

`[discord] conversation = true` にすると、slash command に加えて `@Sawagani ...` のメンションや Bot への DM で会話できます。メンション/DM 宛ての本文は Discord の仕様上 Message Content Intent なしで届くため、Privileged Gateway Intents は OFF のままで構いません。

会話モードでは Sawagani が `tasks.md` / `MEMORY.md` / `config.toml` を読んで状況を説明し、`tasks.md` へのタスク追加や `config.toml` の編集も行えます。`config.toml` の変更は、実行中のデーモンや現在の会話セッションには即時反映されず、次回 `sawagani start` 起動時に反映されます。

強い機能なので、必要に応じて `allowed_user_ids` で会話できるユーザーを制限してください。会話の文脈を消したいときは、メンションまたは DM で `リセット` と送ると、そのチャンネルの会話セッションを作り直します。

### うまくいかないとき

- **`403 Forbidden (error code: 50001): Missing Access`** … 招待時に `applications.commands` スコープが認可されていないか、`guild_id` が間違っています。手順2で両スコープにチェックして再認可し、`guild_id` が本物のサーバーIDかを確認してください。
- **`SAWAGANI_DISCORD_BOT_TOKEN is not set`** … 環境変数が未設定です。手順5の `export` を確認してください。
- **slash command がサーバーに出てこない** … 認可後すぐは反映に時間がかかることがあります。Bot を再起動し、`config.toml` の `guild_id` が招待先サーバーと一致しているか確認してください。

## テスト

```bash
uv run pytest
uv run ty check
```
