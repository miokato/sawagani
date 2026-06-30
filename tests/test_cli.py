"""cli モジュールのユニットテスト。

CLI 境界では、ユーザー操作による中断とプログラムエラーを区別する。
Ctrl+C は正常な停止操作として扱い、スタックトレースを出さず終了コード 130 で終える。
"""

import pytest

from sawagani import cli


class TestMain:
    """main(): CLI エントリとして終了時のふるまいを制御する。"""

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
