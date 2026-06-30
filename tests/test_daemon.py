"""daemon モジュールのユニットテスト。

バックグラウンド実行は PID ファイルとログファイルで軽く管理する。
実プロセスは起動せず、Popen / os.kill を差し替えて判断ロジックを検証する。
"""

from pathlib import Path
from typing import Any

from sawagani import daemon, settings


class FakePopen:
    """daemon.start() で使う subprocess.Popen の最小フェイク。"""

    calls: list[dict[str, Any]] = []

    def __init__(self, cmd, **kwargs):
        self.pid = 4242
        self.poll_result = None
        self.calls.append({"cmd": cmd, "kwargs": kwargs})

    def poll(self):
        return self.poll_result


class TestStart:
    """start(): loop をバックグラウンドプロセスとして起動する。"""

    def test_starts_background_process_and_writes_pid(self, tmp_path, monkeypatch):
        """PID とログパスを data_dir 配下に用意して loop を起動する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        FakePopen.calls.clear()
        monkeypatch.setattr(daemon.subprocess, "Popen", FakePopen)

        result = daemon.start(interval=10, max_ticks=0)

        assert result.started is True
        assert result.pid == 4242
        assert settings.pid_path().read_text(encoding="utf-8") == "4242\n"
        assert settings.log_path().is_file()
        assert FakePopen.calls[0]["cmd"][-5:] == [
            "loop",
            "--interval",
            "10",
            "--max-ticks",
            "0",
        ]

    def test_does_not_start_when_existing_pid_is_alive(self, tmp_path, monkeypatch):
        """生存中の PID ファイルがある場合は多重起動しない。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        settings.pid_path().write_text("123\n", encoding="utf-8")
        monkeypatch.setattr(daemon, "is_process_alive", lambda pid: True)
        FakePopen.calls.clear()
        monkeypatch.setattr(daemon.subprocess, "Popen", FakePopen)

        result = daemon.start(interval=10, max_ticks=0)

        assert result.started is False
        assert result.pid == 123
        assert FakePopen.calls == []

    def test_removes_stale_pid_before_starting(self, tmp_path, monkeypatch):
        """死んだ PID ファイルは掃除してから起動する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        settings.pid_path().write_text("123\n", encoding="utf-8")
        monkeypatch.setattr(daemon, "is_process_alive", lambda pid: False)
        FakePopen.calls.clear()
        monkeypatch.setattr(daemon.subprocess, "Popen", FakePopen)

        result = daemon.start(interval=10, max_ticks=0)

        assert result.started is True
        assert settings.pid_path().read_text(encoding="utf-8") == "4242\n"


class TestStop:
    """stop(): PID ファイルのプロセスへ SIGTERM を送る。"""

    def test_sends_sigterm_and_removes_pid_file(self, tmp_path, monkeypatch):
        """実行中プロセスに停止シグナルを送り PID ファイルを消す。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        settings.pid_path().write_text("123\n", encoding="utf-8")
        sent: list[tuple[int, int]] = []
        monkeypatch.setattr(daemon, "is_process_alive", lambda pid: True)
        monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: sent.append((pid, sig)))

        result = daemon.stop()

        assert result.stopped is True
        assert result.pid == 123
        assert sent == [(123, daemon.signal.SIGTERM)]
        assert not settings.pid_path().exists()

    def test_reports_not_running_without_pid_file(self, tmp_path, monkeypatch):
        """PID ファイルが無ければ停止対象なしとして返す。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))

        result = daemon.stop()

        assert result.stopped is False
        assert result.pid is None


class TestStatus:
    """status(): PID ファイルと生存確認から状態を返す。"""

    def test_running_when_pid_is_alive(self, tmp_path, monkeypatch):
        """PID が生きていれば running と判定する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        settings.pid_path().write_text("123\n", encoding="utf-8")
        monkeypatch.setattr(daemon, "is_process_alive", lambda pid: True)

        result = daemon.status()

        assert result.running is True
        assert result.pid == 123
        assert result.pid_path == settings.pid_path()
        assert result.log_path == settings.log_path()

    def test_stopped_when_pid_file_is_stale(self, tmp_path, monkeypatch):
        """PID が死んでいれば stopped と判定し、古い PID ファイルを消す。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        settings.pid_path().write_text("123\n", encoding="utf-8")
        monkeypatch.setattr(daemon, "is_process_alive", lambda pid: False)

        result = daemon.status()

        assert result.running is False
        assert result.pid == 123
        assert not settings.pid_path().exists()
