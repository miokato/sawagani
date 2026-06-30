"""agent モジュールのユニットテスト。

Red/Green TDD で進める。まずは「やることなし(IDLE)」判定を行う純粋関数
`is_idle()` を対象にする。この関数は応答テキストを受け取り、エージェントが
何もせず IDLE を返したかを判定する。

判定方針（仕様）:
- モデルは前置き（理由説明）を付けてから最終行に `IDLE` を返すことがある。
  そのため「最終の非空行が IDLE」なら True とみなす。
- 空文字や、IDLE で終わらない通常の作業報告は False。
"""

import anyio

from sawagani import agent, config


class TestBuildOptions:
    """build_options(): 設定（config.toml）の許可ツールを実行オプションへ配線する。"""

    def test_allowed_tools_come_from_settings(self, tmp_path, monkeypatch):
        """allowed_tools が load_settings() の値と一致する（設定で制御できる）。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        (tmp_path / config.CONFIG_FILE).write_text(
            '[agent]\nallowed_tools = ["Read"]\n', encoding="utf-8"
        )
        options = agent.build_options()
        assert options.allowed_tools == ["Read"]

    def test_default_includes_web_tools(self, tmp_path, monkeypatch):
        """config.toml が無ければ既定で Web ツールが許可される。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        options = agent.build_options()
        assert "WebSearch" in options.allowed_tools
        assert "WebFetch" in options.allowed_tools


class TestIsIdle:
    """is_idle(): 応答が IDLE（やることなし）かを判定する。"""

    def test_exact_idle(self):
        """`IDLE` だけの応答は True。"""
        assert agent.is_idle("IDLE") is True

    def test_idle_with_preamble(self):
        """前置きが付いても最終行が IDLE なら True。"""
        text = "記録済みのため新たな作業はありません。\n\nIDLE"
        assert agent.is_idle(text) is True

    def test_work_report_is_not_idle(self):
        """通常の作業報告（IDLE で終わらない）は False。"""
        text = "README.md を確認し MEMORY.md に追記しました。"
        assert agent.is_idle(text) is False

    def test_empty_is_not_idle(self):
        """空応答は IDLE とみなさない（False）。"""
        assert agent.is_idle("") is False

    def test_idle_not_final_line_is_not_idle(self):
        """IDLE が最終行でなければ False。"""
        text = "IDLE ですが念のため状況を確認します。"
        assert agent.is_idle(text) is False


class TestSleepUntilNextTick:
    """sleep_until_next_tick(): 待機中の STOP 作成を短い間隔で検知する。"""

    def test_returns_true_when_stop_file_appears_during_wait(self, tmp_path, monkeypatch):
        """STOP が待機中に作られたら、次ティックを待たず停止を返す。"""
        stop_file = tmp_path / config.STOP_FILE
        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float):
            sleep_calls.append(seconds)
            stop_file.touch()

        monkeypatch.setattr(agent.anyio, "sleep", fake_sleep)

        stopped = anyio.run(
            agent.sleep_until_next_tick,
            30,
            stop_file,
            1,
        )

        assert stopped is True
        assert sleep_calls == [1]
