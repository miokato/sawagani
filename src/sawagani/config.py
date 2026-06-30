"""Sawagani の設定を集約するモジュール（設定の責務のみ）。

定数・システムプロンプト・状態ファイルのパス解決をここにまとめる。
コード（src 配下）と実行時データ（tasks.md / MEMORY.md / STOP）は分離する方針で、
状態ファイルはパッケージ内ではなく「データディレクトリ」に置く。
"""

import os
from pathlib import Path

# --- 状態ファイル名（データディレクトリ内での相対名） ---
TASKS_FILE = "tasks.md"   # やること定義（ユーザーが編集）
MEMORY_FILE = "MEMORY.md"  # 実行ログ＝状態（エージェントが追記）
STOP_FILE = "STOP"         # キルスイッチ（存在すればループ停止）

# --- 暴走防止ガード ---
MAX_TURNS_PER_TICK = 12       # 1ティック内のツール連鎖の上限
MIN_INTERVAL_SEC = 60         # --interval の下限（暴走防止）
DEFAULT_INTERVAL_SEC = 1800   # 既定30分
DEFAULT_MAX_TICKS = 48        # 総ティック数の上限（既定30分×48＝約1日）

# 状態ディレクトリを上書きするための環境変数名
HOME_ENV = "SAWAGANI_HOME"

# --- エージェントのシステムプロンプト（人格・手順） ---
SYSTEM_PROMPT = f"""\
あなたは Sawagani という軽量な自律エージェントです。一定間隔で起動されます。
毎回の起動（ハートビート）で次の手順に従ってください。日本語で簡潔に。

1. `{TASKS_FILE}` と `{MEMORY_FILE}` を読む。
2. {MEMORY_FILE} の履歴を踏まえ、今やるべき作業が「ちょうど1つ」あるか判断する。
3. やるべき作業が無ければ、何もせず `IDLE` とだけ返す（余計な出力はしない）。
4. やるべき作業があれば、それを実行し、`{MEMORY_FILE}` の末尾に
   「- <ISO日時> <実施内容の要約>」という形式で1行だけ追記する。
   - 追記は Write ツールで行う（Edit は使わない）。既存の内容は消さず末尾に足すこと。
   - 同じ作業を MEMORY に記録済みなら繰り返さない（重複防止）。

許可されているツールは Read と Write のみ。外部送信や破壊的操作はしないこと。"""


def data_dir() -> Path:
    """状態ファイル（tasks/memory/STOP）を置くデータディレクトリを返す。

    環境変数 ``SAWAGANI_HOME`` があればそれを使い、無ければ実行時のカレント
    ディレクトリを使う。コード（src）とは分離するため、パッケージの場所には依存しない。
    """
    return Path(os.environ.get(HOME_ENV, Path.cwd()))


def stop_path() -> Path:
    """キルスイッチファイルの絶対パスを返す。"""
    return data_dir() / STOP_FILE
