"""Sawagani の作業リスト tasks.md を更新する内部モジュール。"""

from pathlib import Path

from . import settings


def append_task(text: str, source: str) -> Path:
    """tasks.md に外部入力由来のタスクを1行追記する。"""
    task_text = " ".join(text.split())
    if not task_text:
        raise ValueError("task text must not be empty")

    tasks_path = settings.data_dir() / settings.TASKS_FILE
    tasks_path.parent.mkdir(parents=True, exist_ok=True)

    needs_leading_newline = False
    if tasks_path.exists() and tasks_path.stat().st_size > 0:
        with tasks_path.open("rb") as f:
            f.seek(-1, 2)
            needs_leading_newline = f.read(1) != b"\n"

    with tasks_path.open("a", encoding="utf-8") as f:
        if needs_leading_newline:
            f.write("\n")
        f.write(f"- [{source}] {task_text}\n")

    return tasks_path
