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

from . import agent, bootstrap, daemon, settings

INTERRUPT_EXCEPTIONS = (KeyboardInterrupt,)
INTERRUPTED_EXIT_CODE = 130


def parse_args() -> argparse.Namespace:
    loaded_settings = settings.load_settings()  # 既定値は config.toml（無ければ組み込み値）から

    parser = argparse.ArgumentParser(description="Sawagani: ハートビート駆動の自律エージェント")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="初回利用に必要なファイルを作成")
    start_parser = sub.add_parser("start", help="バックグラウンドで常駐ループを開始")
    start_parser.add_argument(
        "--interval", type=int, default=loaded_settings.default_interval_sec,
        help=(
            f"ティック間隔（秒, 下限 {loaded_settings.min_interval_sec}）。"
            f"既定 {loaded_settings.default_interval_sec}"
        ),
    )
    start_parser.add_argument(
        "--max-ticks", type=int, default=0,
        help="総ティック数の上限。0 は無制限。既定 0",
    )
    sub.add_parser("stop", help="バックグラウンド実行を停止")
    sub.add_parser("status", help="バックグラウンド実行の状態を表示")
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
        elif args.command == "start":
            result = daemon.start(args.interval, args.max_ticks)
            print_start_result(result)
        elif args.command == "stop":
            result = daemon.stop()
            print_stop_result(result)
        elif args.command == "status":
            result = daemon.status()
            print_status_result(result)
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


def print_start_result(result: daemon.StartResult) -> None:
    """start コマンドの結果を表示する。"""
    if result.started:
        print(f"started pid={result.pid}")
    else:
        print(f"{result.message} pid={result.pid}")
    print(f"log={result.log_path}")


def print_stop_result(result: daemon.StopResult) -> None:
    """stop コマンドの結果を表示する。"""
    if result.stopped:
        print(f"stopped pid={result.pid}")
    else:
        print(result.message)


def print_status_result(result: daemon.StatusResult) -> None:
    """status コマンドの結果を表示する。"""
    if result.running:
        print(f"running pid={result.pid}")
    else:
        print(result.message)
    print(f"pidfile={result.pid_path}")
    print(f"log={result.log_path}")


if __name__ == "__main__":
    main()
