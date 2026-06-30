"""agent モジュールのユニットテスト。

Red/Green TDD で進める。まずは「やることなし(IDLE)」判定を行う純粋関数
`is_idle()` を対象にする。この関数は応答テキストを受け取り、エージェントが
何もせず IDLE を返したかを判定する。

判定方針（仕様）:
- モデルは前置き（理由説明）を付けてから最終行に `IDLE` を返すことがある。
  そのため「最終の非空行が IDLE」なら True とみなす。
- 空文字や、IDLE で終わらない通常の作業報告は False。
"""

import agent


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
