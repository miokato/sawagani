"""Sawagani: ハートビート駆動の自律エージェント（最小実装）。

一定間隔で自分から起動（ティック）し、tasks.md と MEMORY.md を読んで
必要な作業を1つ実行する。やることが無ければ `IDLE` だけ返して寝る
（check-and-sleep）。「ハートビートはメッセージ」設計で、ティックごとに
合成ユーザーメッセージを同じエージェントへ注入する。

claude CLI のサブスク認証（Claude Max など）を利用するため API キーは不要。
事前に `claude` でログイン済みであること。

実行:
    uv run main.py tick                              # 1ティックだけ（テスト用）
    uv run main.py loop --interval 1800 --max-ticks 48   # 常駐ループ
"""

import argparse
import os
from pathlib import Path

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)

# --- 定数（暴走防止ガード） ---
WORKDIR = Path(__file__).resolve().parent
TASKS_FILE = "tasks.md"
MEMORY_FILE = "MEMORY.md"
STOP_FILE = WORKDIR / "STOP"  # このファイルがあればループを止めるキルスイッチ

MAX_TURNS_PER_TICK = 12       # 1ティック内のツール連鎖の上限
MIN_INTERVAL_SEC = 60         # --interval の下限（暴走防止）
DEFAULT_INTERVAL_SEC = 1800   # 既定30分
DEFAULT_MAX_TICKS = 48        # 総ティック数の上限（既定30分×48＝約1日）

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


def build_options() -> ClaudeAgentOptions:
    """最小・セキュアな実行オプションを組み立てる。"""
    return ClaudeAgentOptions(
        cwd=str(WORKDIR),                 # 作業ディレクトリ固定
        allowed_tools=["Read", "Write"],  # 最小許可リスト
        permission_mode="dontAsk",        # 許可外ツールは自動拒否
        system_prompt=SYSTEM_PROMPT,
        max_turns=MAX_TURNS_PER_TICK,     # 1ティックの上限
    )


def heartbeat_prompt() -> str:
    """ティックごとに注入する合成ユーザーメッセージ（＝ハートビート）。"""
    return (
        "【ハートビート】定期起動です。手順に従って "
        f"{TASKS_FILE} と {MEMORY_FILE} を確認し、"
        "やるべき作業が1つあれば実行して MEMORY に追記、なければ IDLE とだけ返してください。"
    )


async def tick(client: ClaudeSDKClient) -> None:
    """1ティック分の処理。合成メッセージを送り、応答を表示する。"""
    await client.query(heartbeat_prompt())

    parts: list[str] = []
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)

    text = "".join(parts).strip()
    # 最終の非空行が "IDLE" なら「やることなし」と判定（前置きが付いても拾えるように）
    last_line = text.splitlines()[-1].strip() if text else ""
    if last_line == "IDLE":
        print("💤 IDLE（やることなし）")
    else:
        print(text)


async def run_once() -> None:
    """1ティックだけ実行（テスト用）。"""
    async with ClaudeSDKClient(build_options()) as client:
        await tick(client)


async def run_loop(interval: int, max_ticks: int) -> None:
    """一定間隔のハートビート・ループ。文脈を保つため client は1つを使い回す。"""
    interval = max(interval, MIN_INTERVAL_SEC)
    print(f"🫀 ハートビート開始: 間隔 {interval}秒 / 最大 {max_ticks} 回 "
          f"（{STOP_FILE.name} ファイルで停止）\n")

    async with ClaudeSDKClient(build_options()) as client:
        for i in range(1, max_ticks + 1):
            # キルスイッチ確認
            if STOP_FILE.exists():
                print(f"⏹ {STOP_FILE.name} を検出したため停止します。")
                return

            print(f"--- ティック {i}/{max_ticks} ---")
            await tick(client)

            if i < max_ticks:
                await anyio.sleep(interval)

    print(f"\n✅ 最大 {max_ticks} 回に達したため終了しました。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sawagani: ハートビート駆動の自律エージェント")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tick", help="1ティックだけ実行（テスト用）")

    loop_parser = sub.add_parser("loop", help="一定間隔の常駐ループ")
    loop_parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL_SEC,
        help=f"ティック間隔（秒, 下限 {MIN_INTERVAL_SEC}）。既定 {DEFAULT_INTERVAL_SEC}",
    )
    loop_parser.add_argument(
        "--max-ticks", type=int, default=DEFAULT_MAX_TICKS,
        help=f"総ティック数の上限。既定 {DEFAULT_MAX_TICKS}",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "loop":
        anyio.run(run_loop, args.interval, args.max_ticks)
    else:  # "tick" または未指定
        anyio.run(run_once)


if __name__ == "__main__":
    main()
