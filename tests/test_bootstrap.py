"""bootstrap モジュールのユニットテスト。

初回利用に必要なファイルを作る `sawagani init` の中核処理を検証する。
既存ファイルを上書きせず、安全に何度でも実行できることを重視する。
"""

from sawagani import bootstrap, settings


class TestInitProject:
    """init_project(): データディレクトリに初期ファイルを用意する。"""

    def test_creates_initial_files_under_data_dir(self, tmp_path, monkeypatch):
        """tasks.md / config.toml / web-data を data_dir 配下に作る。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))

        result = bootstrap.init_project()

        assert (tmp_path / settings.TASKS_FILE).is_file()
        assert (tmp_path / settings.CONFIG_FILE).is_file()
        assert (tmp_path / settings.DEFAULT_WEB_DATA_DIR).is_dir()
        assert result.created == [
            tmp_path / settings.TASKS_FILE,
            tmp_path / settings.CONFIG_FILE,
            tmp_path / settings.DEFAULT_WEB_DATA_DIR,
        ]

    def test_does_not_overwrite_existing_files(self, tmp_path, monkeypatch):
        """既存の tasks.md / config.toml は内容を保つ。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        tasks_path = tmp_path / settings.TASKS_FILE
        config_path = tmp_path / settings.CONFIG_FILE
        tasks_path.write_text("既存タスク\n", encoding="utf-8")
        config_path.write_text("[agent]\nallowed_tools = [\"Read\"]\n", encoding="utf-8")

        result = bootstrap.init_project()

        assert tasks_path.read_text(encoding="utf-8") == "既存タスク\n"
        assert config_path.read_text(encoding="utf-8") == '[agent]\nallowed_tools = ["Read"]\n'
        assert result.created == [tmp_path / settings.DEFAULT_WEB_DATA_DIR]
        assert result.skipped == [tasks_path, config_path]
