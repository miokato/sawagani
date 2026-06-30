"""cli モジュールのユニットテスト。

CLI 境界では、ユーザー操作による中断とプログラムエラーを区別する。
Ctrl+C は正常な停止操作として扱い、スタックトレースを出さず終了コード 130 で終える。
"""

import pytest

from sawagani import cli


class TestMain:
    """main(): CLI エントリとして終了時のふるまいを制御する。"""

    def test_discord_start_command_runs_discord_bot(self, monkeypatch, capsys):
        """`sawagani discord start` は Discord Bot 起動処理を呼ぶ。"""
        called = False

        def fake_run_from_env():
            nonlocal called
            called = True

        monkeypatch.setattr(cli.discord_bot, "run_from_env", fake_run_from_env)
        monkeypatch.setattr("sys.argv", ["sawagani", "discord", "start"])

        cli.main()

        captured = capsys.readouterr()
        assert called is True
        assert "Discord Bot を開始します" in captured.out

    def test_start_command_runs_daemon_start(self, monkeypatch, capsys):
        """`sawagani start` はバックグラウンド起動処理を呼ぶ。"""
        called: dict[str, int] = {}

        class FakeResult:
            started = True
            pid = 4242
            message = "started"
            log_path = None

        def fake_start(interval: int, max_ticks: int):
            called["interval"] = interval
            called["max_ticks"] = max_ticks
            return FakeResult()

        monkeypatch.setattr(cli.daemon, "start", fake_start)
        monkeypatch.setattr("sys.argv", ["sawagani", "start", "--interval", "10"])

        cli.main()

        captured = capsys.readouterr()
        assert called == {"interval": 10, "max_ticks": 0}
        assert "started pid=4242" in captured.out

    def test_stop_command_runs_daemon_stop(self, monkeypatch, capsys):
        """`sawagani stop` はバックグラウンド停止処理を呼ぶ。"""
        called = False

        class FakeResult:
            stopped = True
            pid = 4242
            message = "stopped"

        def fake_stop():
            nonlocal called
            called = True
            return FakeResult()

        monkeypatch.setattr(cli.daemon, "stop", fake_stop)
        monkeypatch.setattr("sys.argv", ["sawagani", "stop"])

        cli.main()

        captured = capsys.readouterr()
        assert called is True
        assert "stopped pid=4242" in captured.out

    def test_status_command_runs_daemon_status(self, monkeypatch, capsys):
        """`sawagani status` はバックグラウンド状態を表示する。"""
        called = False

        class FakeResult:
            running = True
            pid = 4242
            message = "running"
            pid_path = None
            log_path = None

        def fake_status():
            nonlocal called
            called = True
            return FakeResult()

        monkeypatch.setattr(cli.daemon, "status", fake_status)
        monkeypatch.setattr("sys.argv", ["sawagani", "status"])

        cli.main()

        captured = capsys.readouterr()
        assert called is True
        assert "running pid=4242" in captured.out

    def test_init_command_runs_project_initialization(self, monkeypatch, capsys):
        """`sawagani init` は初期化処理を実行し、結果を表示する。"""
        called = False

        class FakeResult:
            created = []
            skipped = []

        def fake_init_project():
            nonlocal called
            called = True
            return FakeResult()

        monkeypatch.setattr(cli.bootstrap, "init_project", fake_init_project)
        monkeypatch.setattr("sys.argv", ["sawagani", "init"])

        cli.main()

        captured = capsys.readouterr()
        assert called is True
        assert "初期化しました" in captured.out

    def test_keyboard_interrupt_exits_without_traceback(self, monkeypatch, capsys):
        """Ctrl+C はスタックトレースではなく短い停止メッセージで終了する。"""
        class SimulatedInterrupt(Exception):
            """pytest の KeyboardInterrupt 特別扱いを避けるためのテスト用例外。"""

        def interrupted_run(*args, **kwargs):
            raise SimulatedInterrupt

        monkeypatch.setattr(cli.anyio, "run", interrupted_run)
        monkeypatch.setattr(cli, "INTERRUPT_EXCEPTIONS", (SimulatedInterrupt,), raising=False)
        monkeypatch.setattr("sys.argv", ["sawagani", "tick"])

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

        captured = capsys.readouterr()
        assert exc_info.value.code == 130
        assert "停止しました" in captured.err
        assert "Traceback" not in captured.err
