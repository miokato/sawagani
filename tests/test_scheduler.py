"""scheduler モジュールのユニットテスト。

launchd/systemd には実接続せず、生成物と実行コマンドを検証する。
"""

import plistlib
import stat
import sys
from pathlib import Path

import pytest

from sawagani import scheduler, settings


class FakeRunner:
    """subprocess.run 互換の最小 runner。"""

    def __init__(self, returncodes: list[int] | None = None):
        self.calls: list[list[str]] = []
        self.returncodes = returncodes or []

    def __call__(self, argv: list[str]):
        self.calls.append(argv)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        result = Result()
        if self.returncodes:
            result.returncode = self.returncodes.pop(0)
        return result


class TestLaunchdPlist:
    """build_launchd_plist(): LaunchAgent の plist を生成する。"""

    def test_contains_keepalive_runatload_and_environment(self, tmp_path):
        """plist は常駐監視に必要なキーと SAWAGANI_HOME/PATH を含む。"""
        data_dir = tmp_path / "Sawagani Home"
        plist = scheduler.build_launchd_plist(
            interval=60,
            python="/path/to/python",
            path_env="/usr/local/bin:/usr/bin",
            data_dir=data_dir,
            log=tmp_path / "sawagani.log",
            label="com.sawagani.test",
        )

        loaded = plistlib.loads(plist)

        assert loaded["Label"] == "com.sawagani.test"
        assert loaded["RunAtLoad"] is True
        assert loaded["KeepAlive"] is True
        assert loaded["ProgramArguments"] == [
            "/path/to/python",
            "-m",
            "sawagani",
            "serve",
            "--interval",
            "60",
        ]
        assert "loop" not in loaded["ProgramArguments"]
        assert loaded["ProcessType"] == "Background"
        assert loaded["ThrottleInterval"] == 20
        assert loaded["EnvironmentVariables"][settings.HOME_ENV] == str(data_dir)
        assert loaded["EnvironmentVariables"]["PATH"] == "/usr/local/bin:/usr/bin"


class TestSystemdUnit:
    """build_systemd_unit(): systemd ユーザーサービスを生成する。"""

    def test_contains_restart_execstart_and_install_section(self, tmp_path):
        """unit は常駐監視に必要な設定を含む。"""
        data_dir = tmp_path / "Sawagani Home"

        unit = scheduler.build_systemd_unit(
            interval=60,
            python="/path with space/python",
            data_dir=data_dir,
        )

        assert "Restart=always" in unit
        assert "ExecStart=" in unit
        assert " -m sawagani serve --interval 60" in unit
        assert " loop " not in unit
        assert f'Environment="{settings.HOME_ENV}={data_dir}"' in unit
        assert f'WorkingDirectory="{data_dir}"' in unit
        assert "WantedBy=default.target" in unit


class TestSelectBackend:
    """select_backend(): 実行OSに応じた監視バックエンドを選ぶ。"""

    def test_darwin_selects_launchd(self, monkeypatch):
        """macOS では launchd を使う。"""
        monkeypatch.setattr(sys, "platform", "darwin")

        assert scheduler.select_backend() == "launchd"

    def test_linux_selects_systemd(self, monkeypatch):
        """Linux では systemd user service を使う。"""
        monkeypatch.setattr(sys, "platform", "linux")

        assert scheduler.select_backend() == "systemd"

    def test_other_platform_raises(self, monkeypatch):
        """未対応 platform は暗黙に systemd 扱いせず明示的に失敗する。"""
        monkeypatch.setattr(sys, "platform", "win32")

        with pytest.raises(RuntimeError):
            scheduler.select_backend()


class TestInstallInvokesRunner:
    """install(): OS コマンドを runner 経由で呼び出す。"""

    def test_launchd_install_writes_plist_and_bootstraps(self, tmp_path, monkeypatch):
        """launchd では plist を書いて launchctl bootstrap を呼ぶ。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        launch_agents = tmp_path / "LaunchAgents"
        monkeypatch.setattr(scheduler, "select_backend", lambda: "launchd")
        monkeypatch.setattr(scheduler, "launchd_dir", lambda: launch_agents)
        monkeypatch.setattr(scheduler.os, "getuid", lambda: 501)
        runner = FakeRunner()

        result = scheduler.install(interval=60, runner=runner)

        assert result.installed is True
        assert result.service_path.is_file()
        assert stat.S_IMODE(result.service_path.stat().st_mode) == 0o600
        assert runner.calls[0] == ["launchctl", "bootout", f"gui/501/{result.label}"]
        assert runner.calls[1][:4] == ["launchctl", "bootstrap", "gui/501", str(result.service_path)]

    def test_systemd_install_writes_unit_and_enables(self, tmp_path, monkeypatch):
        """systemd では unit を書いて daemon-reload と enable --now を呼ぶ。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        systemd_user = tmp_path / "systemd-user"
        monkeypatch.setattr(scheduler, "select_backend", lambda: "systemd")
        monkeypatch.setattr(scheduler, "systemd_user_dir", lambda: systemd_user)
        runner = FakeRunner()

        result = scheduler.install(interval=60, runner=runner)

        assert result.installed is True
        assert result.service_path.is_file()
        assert runner.calls[0] == ["systemctl", "--user", "daemon-reload"]
        assert runner.calls[1] == ["systemctl", "--user", "enable", "--now", result.label]


class TestInstallIsIdempotent:
    """install(): 既存設定があっても上書きして再登録する。"""

    def test_existing_plist_is_overwritten(self, tmp_path, monkeypatch):
        """同じ LaunchAgent が既にあっても最新内容で上書きする。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        launch_agents = tmp_path / "LaunchAgents"
        monkeypatch.setattr(scheduler, "select_backend", lambda: "launchd")
        monkeypatch.setattr(scheduler, "launchd_dir", lambda: launch_agents)
        monkeypatch.setattr(scheduler.os, "getuid", lambda: 501)
        service_path = scheduler.launchd_service_path(tmp_path)
        service_path.parent.mkdir(parents=True)
        service_path.write_text("old", encoding="utf-8")

        scheduler.install(interval=60, runner=FakeRunner())

        assert service_path.read_bytes() != b"old"


class TestStatusReportsPaused:
    """status(): OS 状態に加えて STOP による一時停止を返す。"""

    def test_status_is_paused_when_stop_file_exists(self, tmp_path, monkeypatch):
        """STOP ファイルがあれば paused=True。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        monkeypatch.setattr(scheduler, "select_backend", lambda: "launchd")
        monkeypatch.setattr(scheduler, "launchd_dir", lambda: tmp_path / "LaunchAgents")
        monkeypatch.setattr(scheduler.os, "getuid", lambda: 501)
        settings.stop_path().touch()

        result = scheduler.status(runner=FakeRunner())

        assert result.paused is True
