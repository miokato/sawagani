"""settings モジュールのユニットテスト。

状態ファイル（tasks/memory/STOP）の置き場所＝データディレクトリの解決を検証する。
コード（src）と実行時データを分離する設計なので、データディレクトリは
環境変数 ``SAWAGANI_HOME`` か、無ければ実行時カレントに基づく（パッケージ位置に依存しない）。
"""

import pytest

from sawagani import settings


class TestDataDir:
    """data_dir(): 状態ファイルを置くディレクトリを解決する。"""

    def test_defaults_to_cwd(self, tmp_path, monkeypatch):
        """SAWAGANI_HOME 未設定なら実行時カレントを使う。"""
        monkeypatch.delenv(settings.HOME_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        assert settings.data_dir().resolve() == tmp_path.resolve()

    def test_uses_env_when_set(self, tmp_path, monkeypatch):
        """SAWAGANI_HOME が設定されていればそれを優先する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        assert settings.data_dir().resolve() == tmp_path.resolve()


class TestStopPath:
    """stop_path(): キルスイッチファイルの絶対パスを返す。"""

    def test_under_data_dir(self, tmp_path, monkeypatch):
        """data_dir 配下の STOP ファイルを指す。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        assert settings.stop_path().resolve() == (tmp_path / settings.STOP_FILE).resolve()


class TestSchedulePath:
    """schedule_path(): 自己予約テーブルの絶対パスを返す。"""

    def test_under_data_dir(self, tmp_path, monkeypatch):
        """data_dir 配下の schedule.md を指す。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))

        assert settings.schedule_path().resolve() == (tmp_path / settings.SCHEDULE_FILE).resolve()


class TestSecretsPath:
    """secrets_path(): Discord Token 用ファイルの場所を返す。"""

    def test_defaults_under_user_config_home(self, monkeypatch, tmp_path):
        """XDG_CONFIG_HOME があればその配下の sawagani/secrets を使う。"""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        assert settings.secrets_path() == tmp_path / "sawagani" / "secrets"


class TestLoadBotToken:
    """load_bot_token(): env または secrets ファイルから Bot Token を読む。"""

    def test_environment_takes_precedence(self, monkeypatch, tmp_path):
        """環境変数があれば secrets ファイルを見ずにその値を使う。"""
        monkeypatch.setenv(settings.DISCORD_BOT_TOKEN_ENV, "env-token")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        assert settings.load_bot_token() == "env-token"

    def test_reads_token_from_secrets_file(self, monkeypatch, tmp_path):
        """環境変数が無い場合は 0600 の secrets ファイルから KEY=VALUE を読む。"""
        monkeypatch.delenv(settings.DISCORD_BOT_TOKEN_ENV, raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = settings.secrets_path()
        path.parent.mkdir(parents=True)
        path.write_text("SAWAGANI_DISCORD_BOT_TOKEN=file-token\n", encoding="utf-8")
        path.chmod(0o600)

        assert settings.load_bot_token() == "file-token"

    def test_rejects_group_or_world_readable_secrets_file(self, monkeypatch, tmp_path):
        """0644 など他者が読める secrets ファイルは拒否する。"""
        monkeypatch.delenv(settings.DISCORD_BOT_TOKEN_ENV, raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = settings.secrets_path()
        path.parent.mkdir(parents=True)
        path.write_text("SAWAGANI_DISCORD_BOT_TOKEN=file-token\n", encoding="utf-8")
        path.chmod(0o644)

        with pytest.raises(RuntimeError, match="chmod 600"):
            settings.load_bot_token()

    def test_raises_with_path_when_token_is_missing(self, monkeypatch, tmp_path):
        """Token が見つからなければ設定先が分かるエラーを出す。"""
        monkeypatch.delenv(settings.DISCORD_BOT_TOKEN_ENV, raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        with pytest.raises(RuntimeError) as exc_info:
            settings.load_bot_token()

        assert str(settings.secrets_path()) in str(exc_info.value)
        assert settings.DISCORD_BOT_TOKEN_ENV in str(exc_info.value)


class TestWebDataDir:
    """web_data_dir(): Web 取得データの保存先ディレクトリを解決する。"""

    def test_defaults_under_data_dir(self, tmp_path, monkeypatch):
        """未設定なら data_dir 配下の既定ディレクトリを使う。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        loaded_settings = settings.load_settings()

        assert settings.web_data_dir(loaded_settings) == tmp_path / "web-data"

    def test_relative_path_is_under_data_dir(self, tmp_path, monkeypatch):
        """相対パス指定は data_dir からの相対として解決する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        (tmp_path / settings.CONFIG_FILE).write_text(
            '[storage]\nweb_data_dir = "saved/pages"\n', encoding="utf-8"
        )

        loaded_settings = settings.load_settings()

        assert settings.web_data_dir(loaded_settings) == tmp_path / "saved" / "pages"

    def test_relative_path_cannot_escape_data_dir(self, tmp_path, monkeypatch):
        """相対パス指定が .. で data_dir の外へ出る設定は拒否する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        loaded_settings = settings.Settings(web_data_dir="../outside")

        try:
            settings.web_data_dir(loaded_settings)
        except ValueError as exc:
            assert "web_data_dir" in str(exc)
        else:
            raise AssertionError("web_data_dir should reject escaping relative paths")


class TestLoadSettings:
    """load_settings(): config.toml があれば読み、無ければ組み込みデフォルトを返す。"""

    def test_defaults_when_no_file(self, tmp_path, monkeypatch):
        """config.toml が無ければデフォルト設定を返す。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))  # 空ディレクトリ
        s = settings.load_settings()
        assert s.allowed_tools == ["Read", "Write", "WebSearch", "WebFetch"]
        assert s.max_turns_per_tick == 12
        assert s.default_interval_sec == 1800
        assert s.min_interval_sec == 60
        assert s.default_max_ticks == 48
        assert s.downloads.allow_bash_downloads is False
        assert s.downloads.allowed_commands == ["curl", "wget"]

    def test_overrides_allowed_tools_from_file(self, tmp_path, monkeypatch):
        """config.toml の allowed_tools が反映される。未指定値はデフォルトのまま。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        (tmp_path / settings.CONFIG_FILE).write_text(
            '[agent]\nallowed_tools = ["Read"]\n', encoding="utf-8"
        )
        s = settings.load_settings()
        assert s.allowed_tools == ["Read"]
        assert s.max_turns_per_tick == 12  # 未指定はデフォルト維持

    def test_overrides_loop_values_from_file(self, tmp_path, monkeypatch):
        """config.toml の [loop] 値が反映される。未指定値はデフォルトのまま。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        (tmp_path / settings.CONFIG_FILE).write_text(
            "[loop]\ndefault_interval_sec = 300\n", encoding="utf-8"
        )
        s = settings.load_settings()
        assert s.default_interval_sec == 300
        assert s.min_interval_sec == 60  # 未指定はデフォルト維持

    def test_overrides_web_data_dir_from_file(self, tmp_path, monkeypatch):
        """config.toml の [storage].web_data_dir が反映される。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        (tmp_path / settings.CONFIG_FILE).write_text(
            '[storage]\nweb_data_dir = "research"\n', encoding="utf-8"
        )

        s = settings.load_settings()

        assert s.web_data_dir == "research"

    def test_overrides_discord_values_from_file(self, tmp_path, monkeypatch):
        """config.toml の [discord] 値が反映される。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        (tmp_path / settings.CONFIG_FILE).write_text(
            "[discord]\n"
            "enabled = true\n"
            "conversation = true\n"
            "guild_id = 111\n"
            "channel_id = 222\n"
            "allowed_user_ids = [333, 444]\n",
            encoding="utf-8",
        )

        s = settings.load_settings()

        assert s.discord.enabled is True
        assert s.discord.conversation is True
        assert s.discord.guild_id == 111
        assert s.discord.channel_id == 222
        assert s.discord.allowed_user_ids == [333, 444]

    def test_overrides_download_values_from_file(self, tmp_path, monkeypatch):
        """config.toml の [downloads] 値が反映される。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        (tmp_path / settings.CONFIG_FILE).write_text(
            "[downloads]\n"
            "allow_bash_downloads = true\n"
            'allowed_commands = ["curl"]\n',
            encoding="utf-8",
        )

        s = settings.load_settings()

        assert s.downloads.allow_bash_downloads is True
        assert s.downloads.allowed_commands == ["curl"]
