"""Sawagani の CLI エントリ（引数解析と起動の責務のみ）。

ハートビート駆動の自律エージェント。一定間隔で起動（ティック）し、tasks.md と
MEMORY.md を読んで必要な作業を1つ実行する。やることが無ければ寝る。

claude CLI のサブスク認証（Claude Max など）を利用するため API キーは不要。
事前に `claude` でログイン済みであること。

実行:
    uv run main.py tick                                  # 1ティックだけ（テスト用）
    uv run main.py loop --interval 1800 --max-ticks 48   # 常駐ループ
"""

import argparse

import anyio

import agent
import config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sawagani: ハートビート駆動の自律エージェント")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tick", help="1ティックだけ実行（テスト用）")

    loop_parser = sub.add_parser("loop", help="一定間隔の常駐ループ")
    loop_parser.add_argument(
        "--interval", type=int, default=config.DEFAULT_INTERVAL_SEC,
        help=f"ティック間隔（秒, 下限 {config.MIN_INTERVAL_SEC}）。既定 {config.DEFAULT_INTERVAL_SEC}",
    )
    loop_parser.add_argument(
        "--max-ticks", type=int, default=config.DEFAULT_MAX_TICKS,
        help=f"総ティック数の上限。既定 {config.DEFAULT_MAX_TICKS}",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "loop":
        anyio.run(agent.run_loop, args.interval, args.max_ticks)
    else:  # "tick" または未指定
        anyio.run(agent.run_once)


if __name__ == "__main__":
    main()
