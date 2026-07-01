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


class TestConversationAuthorization:
    """is_conversation_authorized(): 会話モードの実行可否を判定する。"""

    def test_allows_dm_from_allowed_user(self):
        """DM では guild/channel を見ず、許可ユーザーなら会話を許可する。"""
        discord_settings = settings.DiscordSettings(
            enabled=True,
            conversation=True,
            guild_id=1,
            channel_id=2,
            allowed_user_ids=[3],
        )

        assert discord_bot.is_conversation_authorized(
            discord_settings,
            guild_id=None,
            channel_id=9,
            user_id=3,
            is_dm=True,
        )

    def test_denies_dm_from_unlisted_user(self):
        """DM でも allowed_user_ids がある場合、未登録ユーザーは拒否する。"""
        discord_settings = settings.DiscordSettings(
            enabled=True,
            conversation=True,
            allowed_user_ids=[3],
        )

        assert not discord_bot.is_conversation_authorized(
            discord_settings,
            guild_id=None,
            channel_id=9,
            user_id=4,
            is_dm=True,
        )

    def test_server_authorization_matches_slash_command_authorization(self):
        """サーバー内会話は既存の is_authorized() と同じ制限を使う。"""
        discord_settings = settings.DiscordSettings(
            enabled=True,
            conversation=True,
            guild_id=1,
            channel_id=2,
            allowed_user_ids=[3],
        )

        assert discord_bot.is_conversation_authorized(
            discord_settings,
            guild_id=1,
            channel_id=2,
            user_id=3,
            is_dm=False,
        )
        assert not discord_bot.is_conversation_authorized(
            discord_settings,
            guild_id=1,
            channel_id=9,
            user_id=3,
            is_dm=False,
        )

    def test_denies_when_conversation_is_disabled(self):
        """Discord 連携が有効でも conversation=false なら会話は拒否する。"""
        discord_settings = settings.DiscordSettings(enabled=True, conversation=False)

        assert not discord_bot.is_conversation_authorized(
            discord_settings,
            guild_id=None,
            channel_id=None,
            user_id=3,
            is_dm=True,
        )

    def test_denies_when_discord_is_disabled(self):
        """Discord 連携自体が無効なら会話も拒否する。"""
        discord_settings = settings.DiscordSettings(enabled=False, conversation=True)

        assert not discord_bot.is_conversation_authorized(
            discord_settings,
            guild_id=None,
            channel_id=None,
            user_id=3,
            is_dm=True,
        )


class TestStripBotMention:
    """strip_bot_mention(): 先頭の Bot メンションを取り除く。"""

    def test_strips_normal_mention(self):
        """`<@id>` 形式の先頭メンションを除去して本文だけを返す。"""
        assert discord_bot.strip_bot_mention("<@123> こんにちは", 123) == "こんにちは"

    def test_strips_nickname_mention(self):
        """`<@!id>` 形式の先頭メンションも除去する。"""
        assert discord_bot.strip_bot_mention("<@!123>\n設定を見て", 123) == "設定を見て"

    def test_leaves_non_matching_text_trimmed(self):
        """先頭が対象 Bot のメンションでなければ trim だけ行う。"""
        assert discord_bot.strip_bot_mention(" こんにちは", 123) == "こんにちは"


class TestChunkMessage:
    """chunk_message(): Discord の文字数上限に合わせて返答を分割する。"""

    def test_keeps_short_message_as_single_chunk(self):
        """上限以内のメッセージは1要素のまま返す。"""
        assert discord_bot.chunk_message("こんにちは", limit=2000) == ["こんにちは"]

    def test_splits_long_message_and_preserves_text(self):
        """上限超過のメッセージは分割し、連結すれば元の本文に戻る。"""
        text = "a" * 1999 + "\n" + "b" * 1999 + "\n" + "c" * 10

        chunks = discord_bot.chunk_message(text, limit=2000)

        assert len(chunks) > 1
        assert all(len(chunk) <= 2000 for chunk in chunks)
        assert "".join(chunks) == text

    def test_splits_single_line_over_limit(self):
        """1行だけで上限を超える場合は上限幅でハード分割する。"""
        text = "a" * 4500

        chunks = discord_bot.chunk_message(text, limit=2000)

        assert [len(chunk) for chunk in chunks] == [2000, 2000, 500]
        assert "".join(chunks) == text

    def test_empty_message_returns_one_empty_chunk(self):
        """空応答でも呼び出し側がそのまま送れるよう1要素で返す。"""
        assert discord_bot.chunk_message("", limit=2000) == [""]


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
