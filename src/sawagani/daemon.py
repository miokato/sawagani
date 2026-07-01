"""Sawagani の OS 監視付き常駐ジョブを管理する互換ラッパ。"""

from . import scheduler

StartResult = scheduler.InstallResult
StopResult = scheduler.UninstallResult
StatusResult = scheduler.SchedulerStatus


def start(interval: int, max_ticks: int = 0) -> StartResult:
    """Sawagani loop を launchd/systemd の監視付き常駐として登録する。

    ``max_ticks`` は旧 PID 管理 API との互換引数。OS 監視付き常駐では常に無制限で
    動かすため無視する。
    """
    del max_ticks
    return scheduler.install(interval)


def stop() -> StopResult:
    """Sawagani の OS 監視付き常駐ジョブを解除する。"""
    return scheduler.uninstall()


def status() -> StatusResult:
    """Sawagani の OS 監視付き常駐ジョブ状態を返す。"""
    return scheduler.status()
