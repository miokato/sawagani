"""Sawagani の軽量バックグラウンド実行を管理する内部モジュール。"""

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import settings


@dataclass
class StartResult:
    """start() の実行結果。"""

    started: bool
    pid: int | None
    message: str
    log_path: Path


@dataclass
class StopResult:
    """stop() の実行結果。"""

    stopped: bool
    pid: int | None
    message: str


@dataclass
class StatusResult:
    """status() の実行結果。"""

    running: bool
    pid: int | None
    message: str
    pid_path: Path
    log_path: Path


def read_pid(path: Path | None = None) -> int | None:
    """PID ファイルからプロセスIDを読む。読めなければ None を返す。"""
    pid_file = path or settings.pid_path()
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def remove_pid_file(path: Path | None = None) -> None:
    """PID ファイルがあれば削除する。"""
    pid_file = path or settings.pid_path()
    try:
        pid_file.unlink()
    except FileNotFoundError:
        pass


def is_process_alive(pid: int) -> bool:
    """PID のプロセスが生きているか確認する。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def start(interval: int, max_ticks: int) -> StartResult:
    """Sawagani loop をバックグラウンドプロセスとして起動する。"""
    pid_file = settings.pid_path()
    log_file = settings.log_path()
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    existing_pid = read_pid(pid_file)
    if existing_pid is not None:
        if is_process_alive(existing_pid):
            return StartResult(False, existing_pid, "already running", log_file)
        remove_pid_file(pid_file)

    log_handle = log_file.open("a", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "sawagani",
        "loop",
        "--interval",
        str(interval),
        "--max-ticks",
        str(max_ticks),
    ]
    process = subprocess.Popen(
        cmd,
        cwd=settings.data_dir(),
        stdout=log_handle,
        stderr=log_handle,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    log_handle.close()
    pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
    return StartResult(True, process.pid, "started", log_file)


def stop() -> StopResult:
    """PID ファイルのプロセスへ SIGTERM を送り、PID ファイルを削除する。"""
    pid_file = settings.pid_path()
    pid = read_pid(pid_file)
    if pid is None:
        return StopResult(False, None, "not running")

    if not is_process_alive(pid):
        remove_pid_file(pid_file)
        return StopResult(False, pid, "not running")

    os.kill(pid, signal.SIGTERM)
    remove_pid_file(pid_file)
    return StopResult(True, pid, "stopped")


def status() -> StatusResult:
    """バックグラウンド実行の状態を返す。"""
    pid_file = settings.pid_path()
    log_file = settings.log_path()
    pid = read_pid(pid_file)
    if pid is None:
        return StatusResult(False, None, "stopped", pid_file, log_file)

    if is_process_alive(pid):
        return StatusResult(True, pid, "running", pid_file, log_file)

    remove_pid_file(pid_file)
    return StatusResult(False, pid, "stopped", pid_file, log_file)
