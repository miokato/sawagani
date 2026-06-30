"""Sawagani のハートビート・エージェント本体（実行エンジンの責務）。

「一定間隔で起動し、状態ファイルを読んで作業を1つ実行する」ことだけを担う。
設定は config モジュールから取得し、CLI（引数解析）には依存しない。
"""

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)

from . import config


def build_options() -> ClaudeAgentOptions:
    """最小・セキュアな実行オプションを組み立てる。"""
    return ClaudeAgentOptions(
        cwd=str(config.data_dir()),       # 状態ファイルのあるディレクトリを作業場所に
        allowed_tools=["Read", "Write"],  # 最小許可リスト
        permission_mode="dontAsk",        # 許可外ツールは自動拒否
        system_prompt=config.SYSTEM_PROMPT,
        max_turns=config.MAX_TURNS_PER_TICK,  # 1ティックの上限
    )


def heartbeat_prompt() -> str:
    """ティックごとに注入する合成ユーザーメッセージ（＝ハートビート）。"""
    return (
        "【ハートビート】定期起動です。手順に従って "
        f"{config.TASKS_FILE} と {config.MEMORY_FILE} を確認し、"
        "やるべき作業が1つあれば実行して MEMORY に追記、なければ IDLE とだけ返してください。"
    )


def is_idle(text: str) -> bool:
    """応答テキストが「やることなし(IDLE)」を表すか判定する。

    モデルは前置き（理由説明）を付けてから最終行に `IDLE` を返すことがあるため、
    最終の非空行が `IDLE` のときだけ True とする。空文字や、IDLE で終わらない
    通常の作業報告は False。
    """
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return bool(lines) and lines[-1] == "IDLE"


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
    if is_idle(text):
        print("💤 IDLE（やることなし）")
    else:
        print(text)


async def run_once() -> None:
    """1ティックだけ実行（テスト用）。"""
    async with ClaudeSDKClient(build_options()) as client:
        await tick(client)


async def run_loop(interval: int, max_ticks: int) -> None:
    """一定間隔のハートビート・ループ。文脈を保つため client は1つを使い回す。"""
    interval = max(interval, config.MIN_INTERVAL_SEC)
    stop_file = config.stop_path()
    print(f"🫀 ハートビート開始: 間隔 {interval}秒 / 最大 {max_ticks} 回 "
          f"（{stop_file.name} ファイルで停止）\n")

    async with ClaudeSDKClient(build_options()) as client:
        for i in range(1, max_ticks + 1):
            # キルスイッチ確認
            if stop_file.exists():
                print(f"⏹ {stop_file.name} を検出したため停止します。")
                return

            print(f"--- ティック {i}/{max_ticks} ---")
            await tick(client)

            if i < max_ticks:
                await anyio.sleep(interval)

    print(f"\n✅ 最大 {max_ticks} 回に達したため終了しました。")
