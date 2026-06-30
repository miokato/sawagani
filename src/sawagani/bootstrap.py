"""Sawagani の初回利用に必要なファイルを用意する内部モジュール。"""

from dataclasses import dataclass, field
from pathlib import Path

from . import settings

DEFAULT_TASKS_TEMPLATE = """\
# tasks.md

ここに Sawagani に任せたいことを書いてください。
空のままならエージェントは何もしません。
"""

DEFAULT_CONFIG_TEMPLATE = """\
# Sawagani の設定ファイル（コードを触らず編集できる）。
# 秘密情報は書かないこと（公開リポジトリにコミットされる）。

[agent]
allowed_tools = ["Read", "Write", "WebSearch", "WebFetch"]
max_turns_per_tick = 12

[loop]
default_interval_sec = 1800
min_interval_sec = 60
default_max_ticks = 48

[storage]
web_data_dir = "web-data"

[discord]
# Discord から Sawagani を操作する場合に true。Bot Token は環境変数に設定する。
enabled = false
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
    write_file_if_missing(data_dir / settings.CONFIG_FILE, DEFAULT_CONFIG_TEMPLATE, result)
    ensure_dir_if_missing(settings.web_data_dir(loaded_settings), result)

    return result
