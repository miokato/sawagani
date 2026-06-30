"""tasks モジュールのユニットテスト。

外部入力からの依頼は直接実行せず、まず tasks.md に追記する。
"""

from sawagani import settings, tasks


class TestAppendTask:
    """append_task(): tasks.md に1件の依頼を追記する。"""

    def test_appends_task_with_source(self, tmp_path, monkeypatch):
        """Discord などの入力元を残して tasks.md に追記する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))

        path = tasks.append_task("明日のAIニュースを調べる", source="discord")

        assert path == tmp_path / settings.TASKS_FILE
        assert path.read_text(encoding="utf-8") == "- [discord] 明日のAIニュースを調べる\n"

    def test_adds_newline_when_existing_file_has_no_trailing_newline(self, tmp_path, monkeypatch):
        """既存ファイル末尾に改行が無い場合でも行を壊さず追記する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        path = tmp_path / settings.TASKS_FILE
        path.write_text("- existing", encoding="utf-8")

        tasks.append_task("追加", source="discord")

        assert path.read_text(encoding="utf-8") == "- existing\n- [discord] 追加\n"
