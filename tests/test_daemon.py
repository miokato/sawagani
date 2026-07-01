"""daemon モジュールのユニットテスト。

OS 監視付き常駐化後の daemon は scheduler への互換ラッパとして振る舞う。
実際の launchctl/systemctl は呼ばず、委譲先だけを検証する。
"""

from sawagani import daemon


class TestDaemonWrapper:
    """start/stop/status: scheduler API へ委譲する。"""

    def test_start_delegates_to_scheduler_install(self, monkeypatch):
        """start() は max_ticks を無視し、scheduler.install(interval) を呼ぶ。"""
        called: dict[str, int] = {}

        def fake_install(interval: int):
            called["interval"] = interval
            return "installed"

        monkeypatch.setattr(daemon.scheduler, "install", fake_install)

        assert daemon.start(interval=60, max_ticks=999) == "installed"
        assert called == {"interval": 60}

    def test_stop_delegates_to_scheduler_uninstall(self, monkeypatch):
        """stop() は scheduler.unregister 相当の uninstall() を呼ぶ。"""
        called = False

        def fake_uninstall():
            nonlocal called
            called = True
            return "stopped"

        monkeypatch.setattr(daemon.scheduler, "uninstall", fake_uninstall)

        assert daemon.stop() == "stopped"
        assert called is True

    def test_status_delegates_to_scheduler_status(self, monkeypatch):
        """status() は scheduler.status() の結果をそのまま返す。"""
        called = False

        def fake_status():
            nonlocal called
            called = True
            return "status"

        monkeypatch.setattr(daemon.scheduler, "status", fake_status)

        assert daemon.status() == "status"
        assert called is True
