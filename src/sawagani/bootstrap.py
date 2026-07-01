"""Sawagani の初回利用に必要なファイルを用意する内部モジュール。"""

from dataclasses import dataclass, field
from pathlib import Path

from . import settings

DEFAULT_TASKS_TEMPLATE = """\
# tasks.md

ここに Sawagani に任せたいことを書いてください。
空のままならエージェントは何もしません。
"""

DEFAULT_SCHEDULE_TEMPLATE = """\
# schedule.md

Sawagani に未来の作業を予約したい場合に使います。
例:
- [ ] at:2026-07-02T07:00:00+09:00 | 日報を書く
- [ ] cron:0 9 * * MON | 週次レビュー

予約は次回以降のティック開始時に tasks.md へ追加されます。
"""

DEFAULT_CONFIG_TEMPLATE = """\
# Sawagani の設定ファイル（コードを触らず編集できる）。
# このファイルは sawagani init が生成するローカル設定です。
# リポジトリでは config.example.toml だけを管理し、config.toml は各ユーザーが管理します。

[agent]
allowed_tools = ["Read", "Write", "WebSearch", "WebFetch"]
max_turns_per_tick = 12

[loop]
default_interval_sec = 1800
min_interval_sec = 60
default_max_ticks = 48

[storage]
web_data_dir = "web-data"

[downloads]
# true にすると、LLM が Bash で curl/wget を使って画像や PDF などを取得できます。
# 個人利用向けの緩い許可です。取得物は自己責任で扱ってください。
allow_bash_downloads = false
allowed_commands = ["curl", "wget"]

[discord]
# Discord から Sawagani を操作する場合に true。Bot Token は環境変数に設定する。
enabled = false
# メンション/DM で Sawagani と会話する場合に true。
# 有効にすると会話から config.toml / tasks.md を編集できるため、allowed_user_ids で利用者を絞る。
conversation = false
# guild_id = 123456789012345678
# channel_id = 123456789012345678
# allowed_user_ids = [123456789012345678]
"""


@dataclass
class InitResult:
    """init_project() の実行結果。"""

    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def write_file_if_missing(path: Path, content: str, result: InitResult) -> None:
    """ファイルが無ければ作り、既存なら上書きしない。"""
    if path.exists():
        result.skipped.append(path)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    result.created.append(path)


def ensure_dir_if_missing(path: Path, result: InitResult) -> None:
    """ディレクトリが無ければ作り、既存なら上書きしない。"""
    if path.exists():
        result.skipped.append(path)
        return

    path.mkdir(parents=True, exist_ok=True)
    result.created.append(path)


def init_project() -> InitResult:
    """データディレクトリに初期ファイルを作成する。"""
    result = InitResult()
    data_dir = settings.data_dir()
    loaded_settings = settings.load_settings()

    write_file_if_missing(data_dir / settings.TASKS_FILE, DEFAULT_TASKS_TEMPLATE, result)
    write_file_if_missing(data_dir / settings.SCHEDULE_FILE, DEFAULT_SCHEDULE_TEMPLATE, result)
    write_file_if_missing(data_dir / settings.CONFIG_FILE, DEFAULT_CONFIG_TEMPLATE, result)
    ensure_dir_if_missing(settings.web_data_dir(loaded_settings), result)

    return result
