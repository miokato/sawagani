"""config モジュールのユニットテスト。

状態ファイル（tasks/memory/STOP）の置き場所＝データディレクトリの解決を検証する。
コード（src）と実行時データを分離する設計なので、データディレクトリは
環境変数 ``SAWAGANI_HOME`` か、無ければ実行時カレントに基づく（パッケージ位置に依存しない）。
"""

from sawagani import config


class TestDataDir:
    """data_dir(): 状態ファイルを置くディレクトリを解決する。"""

    def test_defaults_to_cwd(self, tmp_path, monkeypatch):
        """SAWAGANI_HOME 未設定なら実行時カレントを使う。"""
        monkeypatch.delenv(config.HOME_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        assert config.data_dir().resolve() == tmp_path.resolve()

    def test_uses_env_when_set(self, tmp_path, monkeypatch):
        """SAWAGANI_HOME が設定されていればそれを優先する。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        assert config.data_dir().resolve() == tmp_path.resolve()


class TestStopPath:
    """stop_path(): キルスイッチファイルの絶対パスを返す。"""

    def test_under_data_dir(self, tmp_path, monkeypatch):
        """data_dir 配下の STOP ファイルを指す。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        assert config.stop_path().resolve() == (tmp_path / config.STOP_FILE).resolve()


class TestWebDataDir:
    """web_data_dir(): Web 取得データの保存先ディレクトリを解決する。"""

    def test_defaults_under_data_dir(self, tmp_path, monkeypatch):
        """未設定なら data_dir 配下の既定ディレクトリを使う。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        settings = config.load_settings()

        assert config.web_data_dir(settings) == tmp_path / "web-data"

    def test_relative_path_is_under_data_dir(self, tmp_path, monkeypatch):
        """相対パス指定は data_dir からの相対として解決する。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        (tmp_path / config.CONFIG_FILE).write_text(
            '[storage]\nweb_data_dir = "saved/pages"\n', encoding="utf-8"
        )

        settings = config.load_settings()

        assert config.web_data_dir(settings) == tmp_path / "saved" / "pages"

    def test_relative_path_cannot_escape_data_dir(self, tmp_path, monkeypatch):
        """相対パス指定が .. で data_dir の外へ出る設定は拒否する。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        settings = config.Settings(web_data_dir="../outside")

        try:
            config.web_data_dir(settings)
        except ValueError as exc:
            assert "web_data_dir" in str(exc)
        else:
            raise AssertionError("web_data_dir should reject escaping relative paths")


class TestLoadSettings:
    """load_settings(): config.toml があれば読み、無ければ組み込みデフォルトを返す。"""

    def test_defaults_when_no_file(self, tmp_path, monkeypatch):
        """config.toml が無ければデフォルト設定を返す。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))  # 空ディレクトリ
        s = config.load_settings()
        assert s.allowed_tools == ["Read", "Write", "WebSearch", "WebFetch"]
        assert s.max_turns_per_tick == 12
        assert s.default_interval_sec == 1800
        assert s.min_interval_sec == 60
        assert s.default_max_ticks == 48

    def test_overrides_allowed_tools_from_file(self, tmp_path, monkeypatch):
        """config.toml の allowed_tools が反映される。未指定値はデフォルトのまま。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        (tmp_path / config.CONFIG_FILE).write_text(
            '[agent]\nallowed_tools = ["Read"]\n', encoding="utf-8"
        )
        s = config.load_settings()
        assert s.allowed_tools == ["Read"]
        assert s.max_turns_per_tick == 12  # 未指定はデフォルト維持

    def test_overrides_loop_values_from_file(self, tmp_path, monkeypatch):
        """config.toml の [loop] 値が反映される。未指定値はデフォルトのまま。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        (tmp_path / config.CONFIG_FILE).write_text(
            "[loop]\ndefault_interval_sec = 300\n", encoding="utf-8"
        )
        s = config.load_settings()
        assert s.default_interval_sec == 300
        assert s.min_interval_sec == 60  # 未指定はデフォルト維持

    def test_overrides_web_data_dir_from_file(self, tmp_path, monkeypatch):
        """config.toml の [storage].web_data_dir が反映される。"""
        monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
        (tmp_path / config.CONFIG_FILE).write_text(
            '[storage]\nweb_data_dir = "research"\n', encoding="utf-8"
        )

        s = config.load_settings()

        assert s.web_data_dir == "research"
