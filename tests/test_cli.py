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
        """`sawagani start` は OS 監視付き常駐の登録処理を呼ぶ。"""
        called: dict[str, int] = {}

        class FakeResult:
            installed = True
            message = "installed"
            backend = "launchd"
            label = "com.sawagani.test"
            service_path = None
            log_path = None

        def fake_start(interval: int, max_ticks: int = 0):
            called["interval"] = interval
            return FakeResult()

        monkeypatch.setattr(cli.daemon, "start", fake_start)
        monkeypatch.setattr("sys.argv", ["sawagani", "start", "--interval", "10"])

        cli.main()

        captured = capsys.readouterr()
        assert called == {"interval": 10}
        assert "installed backend=launchd" in captured.out

    def test_serve_command_runs_integrated_service(self, monkeypatch):
        """`sawagani serve` は統合サービス本体を前面実行する。"""
        called: dict[str, int] = {}

        async def fake_run_service(interval: int):
            called["interval"] = interval

        real_anyio_run = cli.anyio.run

        def fake_anyio_run(func, *args):
            real_anyio_run(func, *args)

        monkeypatch.setattr(cli.agent, "run_service", fake_run_service)
        monkeypatch.setattr(cli.anyio, "run", fake_anyio_run)
        monkeypatch.setattr("sys.argv", ["sawagani", "serve", "--interval", "15"])

        cli.main()

        assert called == {"interval": 15}

    def test_stop_command_runs_daemon_stop(self, monkeypatch, capsys):
        """`sawagani stop` はバックグラウンド停止処理を呼ぶ。"""
        called = False

        class FakeResult:
            stopped = True
            message = "stopped"
            backend = "launchd"
            label = "com.sawagani.test"
            service_path = None

        def fake_stop():
            nonlocal called
            called = True
            return FakeResult()

        monkeypatch.setattr(cli.daemon, "stop", fake_stop)
        monkeypatch.setattr("sys.argv", ["sawagani", "stop"])

        cli.main()

        captured = capsys.readouterr()
        assert called is True
        assert "stopped backend=launchd" in captured.out

    def test_status_command_runs_daemon_status(self, monkeypatch, capsys):
        """`sawagani status` はバックグラウンド状態を表示する。"""
        called = False

        class FakeResult:
            registered = True
            running = True
            paused = False
            message = "running"
            backend = "launchd"
            label = "com.sawagani.test"
            service_path = None
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
        assert "running backend=launchd" in captured.out

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
