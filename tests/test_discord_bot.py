"""discord_bot モジュールのユニットテスト。

Discord への実接続は行わず、権限チェックとコマンド処理の中核を検証する。
"""

import anyio
import pytest

from sawagani import daemon, discord_bot, settings


class TestBotToken:
    """bot_token(): Discord Bot Token を環境変数から読む。"""

    def test_reads_token_from_environment(self, monkeypatch):
        """SAWAGANI_DISCORD_BOT_TOKEN が設定されていればその値を返す。"""
        monkeypatch.setenv(discord_bot.DISCORD_BOT_TOKEN_ENV, "token")

        assert discord_bot.bot_token() == "token"

    def test_raises_when_token_is_missing(self, monkeypatch):
        """Token 未設定なら起動前に分かりやすく失敗する。"""
        monkeypatch.delenv(discord_bot.DISCORD_BOT_TOKEN_ENV, raising=False)

        with pytest.raises(RuntimeError):
            discord_bot.bot_token()


class TestAuthorization:
    """is_authorized(): Discord コマンドの実行可否を判定する。"""

    def test_allows_matching_guild_channel_and_user(self):
        """設定された guild/channel/user が一致すれば許可する。"""
        discord_settings = settings.DiscordSettings(
            enabled=True,
            guild_id=1,
            channel_id=2,
            allowed_user_ids=[3],
        )

        assert discord_bot.is_authorized(discord_settings, guild_id=1, channel_id=2, user_id=3)

    def test_denies_unlisted_user(self):
        """allowed_user_ids がある場合、未登録ユーザーは拒否する。"""
        discord_settings = settings.DiscordSettings(enabled=True, allowed_user_ids=[3])

        assert not discord_bot.is_authorized(discord_settings, guild_id=1, channel_id=2, user_id=4)

    def test_denies_wrong_channel(self):
        """channel_id が設定されている場合、別チャンネルからの実行は拒否する。"""
        discord_settings = settings.DiscordSettings(enabled=True, channel_id=2)

        assert not discord_bot.is_authorized(discord_settings, guild_id=1, channel_id=9, user_id=3)

    def test_denies_when_discord_is_disabled(self):
        """Discord 連携が無効なら拒否する。"""
        discord_settings = settings.DiscordSettings(enabled=False)

        assert not discord_bot.is_authorized(discord_settings, guild_id=1, channel_id=2, user_id=3)


class TestCommands:
    """Discord slash command から呼ばれる中核処理。"""

    def test_handle_task_appends_to_tasks(self, tmp_path, monkeypatch):
        """task コマンドは tasks.md に依頼を追記する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))

        message = discord_bot.handle_task("AIニュースを調べる")

        assert "tasks.md に追加しました" in message
        assert "AIニュースを調べる" in (tmp_path / settings.TASKS_FILE).read_text(encoding="utf-8")

    def test_format_status_running(self, tmp_path):
        """status コマンドは daemon.status() の結果を短く整形する。"""
        result = daemon.StatusResult(
            running=True,
            pid=123,
            message="running",
            pid_path=tmp_path / "sawagani.pid",
            log_path=tmp_path / "sawagani.log",
        )

        assert discord_bot.format_status(result) == "running pid=123"

    def test_handle_tick_runs_once(self, monkeypatch):
        """tick コマンドは agent.run_once() を1回実行する。"""
        called = False

        async def fake_run_once():
            nonlocal called
            called = True

        monkeypatch.setattr(discord_bot.agent, "run_once", fake_run_once)

        message = anyio.run(discord_bot.handle_tick)

        assert called is True
        assert "tick を実行しました" in message
