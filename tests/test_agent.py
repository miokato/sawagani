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
from claude_agent_sdk import AssistantMessage, TextBlock

from sawagani import agent, settings


class FakeClient:
    """tick() に必要な最小の ClaudeSDKClient 互換オブジェクト。"""

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.queries: list[str] = []

    async def query(self, prompt: str):
        self.queries.append(prompt)

    async def receive_response(self):
        yield AssistantMessage(
            content=[TextBlock(self.response_text)],
            model="test",
        )


class TestBuildOptions:
    """build_options(): 設定（config.toml）の許可ツールを実行オプションへ配線する。"""

    def test_allowed_tools_come_from_settings(self, tmp_path, monkeypatch):
        """allowed_tools が load_settings() の値と一致する（設定で制御できる）。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        (tmp_path / settings.CONFIG_FILE).write_text(
            '[agent]\nallowed_tools = ["Read"]\n', encoding="utf-8"
        )
        options = agent.build_options()
        assert options.allowed_tools == ["Read"]

    def test_default_includes_web_tools(self, tmp_path, monkeypatch):
        """config.toml が無ければ既定で Web ツールが許可される。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        options = agent.build_options()
        assert "WebSearch" in options.allowed_tools
        assert "WebFetch" in options.allowed_tools

    def test_write_tools_are_guarded_by_hook(self, tmp_path, monkeypatch):
        """Write/Edit/MultiEdit/Bash は PreToolUse hook で保存先境界を検査する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))

        options = agent.build_options()

        assert options.hooks is not None
        matchers = options.hooks["PreToolUse"]
        assert matchers[0].matcher == "Write|Edit|MultiEdit|Bash"
        assert options.add_dirs == [tmp_path / "web-data"]


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


class TestStorageWriteGuard:
    """make_storage_write_guard(): LLM の変更先を保存先ディレクトリ以下に制限する。"""

    def test_allows_write_under_web_data_dir(self, tmp_path):
        """保存先ディレクトリ配下への Write は許可する。"""
        web_data_dir = tmp_path / "web-data"
        guard = agent.make_storage_write_guard(web_data_dir)

        result = anyio.run(
            guard,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(web_data_dir / "page.md")},
            },
            "tool-1",
            {"signal": None},
        )

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_denies_write_outside_web_data_dir(self, tmp_path):
        """MEMORY.md など保存先外への Write は拒否する。"""
        web_data_dir = tmp_path / "web-data"
        guard = agent.make_storage_write_guard(web_data_dir)

        result = anyio.run(
            guard,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(tmp_path / settings.MEMORY_FILE)},
            },
            "tool-1",
            {"signal": None},
        )

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_denies_bash_because_write_scope_cannot_be_proven(self, tmp_path):
        """Bash は任意のファイル変更ができるため、保存先境界を守る目的では拒否する。"""
        guard = agent.make_storage_write_guard(tmp_path / "web-data")

        result = anyio.run(
            guard,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "touch web-data/page.md"},
            },
            "tool-1",
            {"signal": None},
        )

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestWriteGuard:
    """make_write_guard(): 会話モード向けに許可ファイルと許可ディレクトリを制限する。"""

    def test_allows_config_file(self, tmp_path, monkeypatch):
        """許可ファイルとして渡した config.toml への Write は許可する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        guard = agent.make_write_guard(
            allowed_dirs=[tmp_path / "web-data"],
            allowed_files=[tmp_path / settings.CONFIG_FILE, tmp_path / settings.TASKS_FILE],
        )

        result = anyio.run(
            guard,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(tmp_path / settings.CONFIG_FILE)},
            },
            "tool-1",
            {"signal": None},
        )

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_allows_tasks_file(self, tmp_path, monkeypatch):
        """許可ファイルとして渡した tasks.md への Edit は許可する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        guard = agent.make_write_guard(
            allowed_dirs=[tmp_path / "web-data"],
            allowed_files=[tmp_path / settings.CONFIG_FILE, tmp_path / settings.TASKS_FILE],
        )

        result = anyio.run(
            guard,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": settings.TASKS_FILE},
            },
            "tool-1",
            {"signal": None},
        )

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_allows_write_under_allowed_directory(self, tmp_path, monkeypatch):
        """許可ディレクトリ配下への Write は許可する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        web_data_dir = tmp_path / "web-data"
        guard = agent.make_write_guard(
            allowed_dirs=[web_data_dir],
            allowed_files=[tmp_path / settings.CONFIG_FILE, tmp_path / settings.TASKS_FILE],
        )

        result = anyio.run(
            guard,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(web_data_dir / "page.md")},
            },
            "tool-1",
            {"signal": None},
        )

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_denies_write_outside_allowed_paths(self, tmp_path, monkeypatch):
        """許可ファイルでも許可ディレクトリ配下でもない Write は拒否する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        guard = agent.make_write_guard(
            allowed_dirs=[tmp_path / "web-data"],
            allowed_files=[tmp_path / settings.CONFIG_FILE, tmp_path / settings.TASKS_FILE],
        )

        result = anyio.run(
            guard,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(tmp_path / settings.MEMORY_FILE)},
            },
            "tool-1",
            {"signal": None},
        )

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_denies_bash(self, tmp_path):
        """Bash は書き込み範囲を保証できないため、会話モードでも拒否する。"""
        guard = agent.make_write_guard(
            allowed_dirs=[tmp_path / "web-data"],
            allowed_files=[tmp_path / settings.CONFIG_FILE, tmp_path / settings.TASKS_FILE],
        )

        result = anyio.run(
            guard,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "touch config.toml"},
            },
            "tool-1",
            {"signal": None},
        )

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestBuildChatOptions:
    """build_chat_options(): Discord 会話用の権限とプロンプトを組み立てる。"""

    def test_chat_tools_include_read_write_edit_and_web_only(self, tmp_path, monkeypatch):
        """会話では Read/Write/Edit と、設定で許可された Web ツールだけを使える。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        (tmp_path / settings.CONFIG_FILE).write_text(
            '[agent]\nallowed_tools = ["Read", "Bash", "WebSearch"]\n',
            encoding="utf-8",
        )

        options = agent.build_chat_options()

        assert options.allowed_tools == ["Read", "Write", "Edit", "WebSearch"]

    def test_write_tools_are_guarded_by_hook(self, tmp_path, monkeypatch):
        """会話モードの Write/Edit/Bash は PreToolUse hook で保存先境界を検査する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))

        options = agent.build_chat_options()

        assert options.hooks is not None
        matchers = options.hooks["PreToolUse"]
        assert matchers[0].matcher == agent.WRITE_GUARD_MATCHER
        assert options.add_dirs == [tmp_path / "web-data"]


class TestRunChatTurn:
    """run_chat_turn(): 会話1ターンの応答テキストを返す。"""

    def test_returns_assistant_text(self):
        """ClaudeSDKClient 互換オブジェクトの応答テキストを連結して返す。"""
        client = FakeClient("設定を確認しました。")

        reply = anyio.run(agent.run_chat_turn, client, "今の設定を教えて")

        assert reply == "設定を確認しました。"
        assert client.queries == ["今の設定を教えて"]


class TestTick:
    """tick(): LLM 応答の表示と MEMORY 追記を担う。"""

    def test_appends_work_report_to_memory(self, tmp_path, monkeypatch):
        """作業報告はアプリ本体が MEMORY.md に1行追記する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        client = FakeClient("ページを取得し web-data/page.md に保存しました。\n出典: https://example.com")

        anyio.run(agent.tick, client)

        memory = (tmp_path / settings.MEMORY_FILE).read_text(encoding="utf-8")
        assert "ページを取得し web-data/page.md に保存しました。" in memory
        assert "出典: https://example.com" in memory
        assert len(memory.strip().splitlines()) == 1

    def test_idle_does_not_append_memory(self, tmp_path, monkeypatch):
        """IDLE 応答は作業実施ではないため MEMORY.md を作らない。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        client = FakeClient("IDLE")

        anyio.run(agent.tick, client)

        assert not (tmp_path / settings.MEMORY_FILE).exists()


class TestSleepUntilNextTick:
    """sleep_until_next_tick(): 待機中の STOP 作成を短い間隔で検知する。"""

    def test_returns_true_when_stop_file_appears_during_wait(self, tmp_path, monkeypatch):
        """STOP が待機中に作られたら、次ティックを待たず停止を返す。"""
        stop_file = tmp_path / settings.STOP_FILE
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


class TestTickRange:
    """tick_range(): ループ回数の範囲を決める。"""

    def test_positive_max_ticks_is_finite(self):
        """正の max_ticks は 1 始まりの有限範囲にする。"""
        assert list(agent.tick_range(3)) == [1, 2, 3]

    def test_zero_max_ticks_is_unbounded(self):
        """0 はバックグラウンド運用向けの無制限ループとして扱う。"""
        ticks = agent.tick_range(0)

        assert [next(ticks), next(ticks), next(ticks)] == [1, 2, 3]
