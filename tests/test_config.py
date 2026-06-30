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
