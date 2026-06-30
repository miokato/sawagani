"""Sawagani の CLI エントリ（引数解析と起動の責務のみ）。

ハートビート駆動の自律エージェント。一定間隔で起動（ティック）し、tasks.md と
MEMORY.md を読んで必要な作業を1つ実行する。やることが無ければ寝る。

claude CLI のサブスク認証（Claude Max など）を利用するため API キーは不要。
事前に `claude` でログイン済みであること。

実行:
    uv run sawagani tick                                  # 1ティックだけ（テスト用）
    uv run sawagani loop --interval 1800 --max-ticks 48   # 常駐ループ
"""

import argparse
import sys

import anyio

from . import agent, bootstrap, settings

INTERRUPT_EXCEPTIONS = (KeyboardInterrupt,)
INTERRUPTED_EXIT_CODE = 130


def parse_args() -> argparse.Namespace:
    loaded_settings = settings.load_settings()  # 既定値は config.toml（無ければ組み込み値）から

    parser = argparse.ArgumentParser(description="Sawagani: ハートビート駆動の自律エージェント")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="初回利用に必要なファイルを作成")
    sub.add_parser("tick", help="1ティックだけ実行（テスト用）")

    loop_parser = sub.add_parser("loop", help="一定間隔の常駐ループ")
    loop_parser.add_argument(
        "--interval", type=int, default=loaded_settings.default_interval_sec,
        help=(
            f"ティック間隔（秒, 下限 {loaded_settings.min_interval_sec}）。"
            f"既定 {loaded_settings.default_interval_sec}"
        ),
    )
    loop_parser.add_argument(
        "--max-ticks", type=int, default=loaded_settings.default_max_ticks,
        help=f"総ティック数の上限。既定 {loaded_settings.default_max_ticks}",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "init":
            result = bootstrap.init_project()
            print_init_result(result)
        elif args.command == "loop":
            anyio.run(agent.run_loop, args.interval, args.max_ticks)
        else:  # "tick" または未指定
            anyio.run(agent.run_once)
    except INTERRUPT_EXCEPTIONS:
        print("\n停止しました。", file=sys.stderr)
        raise SystemExit(INTERRUPTED_EXIT_CODE) from None


def print_init_result(result: bootstrap.InitResult) -> None:
    """init コマンドの結果を表示する。"""
    print("初期化しました。")
    for path in result.created:
        print(f"  created: {path}")
    for path in result.skipped:
        print(f"  exists:  {path}")


if __name__ == "__main__":
    main()
