"""schedule モジュールのユニットテスト。

schedule.md を永続的な自己予約テーブルとして扱い、期限到来分を tasks.md へ注入する。
"""

from datetime import datetime

from sawagani import schedule, settings


class TestParseEntries:
    """parse_entries(): schedule.md の有効行を Entry にする。"""

    def test_parses_at_and_cron_entries(self):
        """at/cron 行を読み取り、壊れた行は無視する。"""
        text = "\n".join(
            [
                "- [ ] at:2026-07-02T07:00:00+09:00 | 日報を書く",
                "- [ ] cron:0 9 * * MON last:2026-07-01T09:00:00+09:00 | 週次レビュー",
                "not schedule",
            ]
        )

        entries = schedule.parse_entries(text)

        assert [entry.kind for entry in entries] == ["at", "cron"]
        assert entries[0].task == "日報を書く"
        assert entries[1].last is not None


class TestIsDue:
    """is_due(): 予約が期限到来しているか判定する。"""

    def test_at_past_is_due_and_future_is_not(self):
        """at は now 以上なら due。timezone なしはローカルタイムとして扱う。"""
        now = datetime.fromisoformat("2026-07-02T08:00:00+09:00")
        past = schedule.parse_entries("- [ ] at:2026-07-02T07:00:00 | past")[0]
        future = schedule.parse_entries("- [ ] at:2026-07-02T09:00:00+09:00 | future")[0]

        assert schedule.is_due(past, now) is True
        assert schedule.is_due(future, now) is False

    def test_cron_uses_last_to_find_next_time(self):
        """cron は last から次回時刻を求める。"""
        entry = schedule.parse_entries(
            "- [ ] cron:0 9 * * * last:2026-07-01T09:00:00+09:00 | 朝の確認"
        )[0]

        assert schedule.is_due(entry, datetime.fromisoformat("2026-07-02T08:59:00+09:00")) is False
        assert schedule.is_due(entry, datetime.fromisoformat("2026-07-02T09:00:00+09:00")) is True


class TestFireDue:
    """fire_due(): due な予約を tasks.md に追記し、schedule.md を更新する。"""

    def test_fires_due_at_and_marks_done(self, tmp_path, monkeypatch):
        """期限到来した at 予約は tasks.md に追記され、[x] になる。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        settings.schedule_path().write_text(
            "- [ ] at:2026-07-02T07:00:00+09:00 | 日報を書く\n",
            encoding="utf-8",
        )

        fired = schedule.fire_due(datetime.fromisoformat("2026-07-02T08:00:00+09:00"))

        assert fired == ["日報を書く"]
        assert "[x] at:2026-07-02T07:00:00+09:00 | 日報を書く" in settings.schedule_path().read_text(
            encoding="utf-8"
        )
        assert "[schedule] 日報を書く" in (tmp_path / settings.TASKS_FILE).read_text(encoding="utf-8")

    def test_cron_initializes_last_without_firing(self, tmp_path, monkeypatch):
        """last が無い cron 行は初回観測で last を追記するだけで発火しない。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        settings.schedule_path().write_text(
            "- [ ] cron:0 9 * * * | 朝の確認\n",
            encoding="utf-8",
        )

        fired = schedule.fire_due(datetime.fromisoformat("2026-07-02T08:00:00+09:00"))

        assert fired == []
        assert "last:2026-07-02T08:00:00+09:00" in settings.schedule_path().read_text(encoding="utf-8")
        assert not (tmp_path / settings.TASKS_FILE).exists()

    def test_due_cron_updates_last_and_appends_task(self, tmp_path, monkeypatch):
        """期限到来した cron 予約は last を更新して tasks.md に追記する。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))
        settings.schedule_path().write_text(
            "- [ ] cron:0 9 * * * last:2026-07-01T09:00:00+09:00 | 朝の確認\n",
            encoding="utf-8",
        )

        fired = schedule.fire_due(datetime.fromisoformat("2026-07-02T09:00:00+09:00"))

        assert fired == ["朝の確認"]
        assert "last:2026-07-02T09:00:00+09:00" in settings.schedule_path().read_text(encoding="utf-8")
        assert "[schedule] 朝の確認" in (tmp_path / settings.TASKS_FILE).read_text(encoding="utf-8")

    def test_missing_schedule_file_does_nothing(self, tmp_path, monkeypatch):
        """schedule.md がなければ何もしない。"""
        monkeypatch.setenv(settings.HOME_ENV, str(tmp_path))

        assert schedule.fire_due(datetime.fromisoformat("2026-07-02T09:00:00+09:00")) == []
