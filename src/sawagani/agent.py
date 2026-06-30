"""Sawagani のハートビート・エージェント本体（実行エンジンの責務）。

「一定間隔で起動し、状態ファイルを読んで作業を1つ実行する」ことだけを担う。
設定は settings モジュールから取得し、CLI（引数解析）には依存しない。
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    TextBlock,
)

from . import settings

WRITE_TOOL_NAMES = {"Write", "Edit", "MultiEdit"}
WRITE_GUARD_MATCHER = "Write|Edit|MultiEdit|Bash"


def build_options() -> ClaudeAgentOptions:
    """最小・セキュアな実行オプションを組み立てる。

    許可ツールやガード値は config.toml（無ければ組み込みデフォルト）から読む。
    """
    loaded_settings = settings.load_settings()
    web_data_dir = settings.web_data_dir(loaded_settings)
    web_data_dir.mkdir(parents=True, exist_ok=True)

    return ClaudeAgentOptions(
        cwd=str(settings.data_dir()),                # 状態ファイルのあるディレクトリを作業場所に
        allowed_tools=loaded_settings.allowed_tools,  # 設定で許可されたツールのみ
        permission_mode="dontAsk",             # 許可外ツールは自動拒否
        system_prompt=settings.system_prompt(web_data_dir),
        max_turns=loaded_settings.max_turns_per_tick,  # 1ティックの上限
        add_dirs=[web_data_dir],
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher=WRITE_GUARD_MATCHER,
                    hooks=[make_storage_write_guard(web_data_dir)],
                )
            ]
        },
    )


def heartbeat_prompt() -> str:
    """ティックごとに注入する合成ユーザーメッセージ（＝ハートビート）。"""
    return (
        "【ハートビート】定期起動です。手順に従って "
        f"{settings.TASKS_FILE} と {settings.MEMORY_FILE} を確認し、"
        "やるべき作業が1つあれば実行して要約を返し、なければ IDLE とだけ返してください。"
        "MEMORY への追記はアプリ本体が行うため、あなたは変更しないでください。"
    )


def is_idle(text: str) -> bool:
    """応答テキストが「やることなし(IDLE)」を表すか判定する。

    モデルは前置き（理由説明）を付けてから最終行に `IDLE` を返すことがあるため、
    最終の非空行が `IDLE` のときだけ True とする。空文字や、IDLE で終わらない
    通常の作業報告は False。
    """
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return bool(lines) and lines[-1] == "IDLE"


def hook_permission(decision: str, reason: str | None = None) -> dict[str, Any]:
    """PreToolUse hook の許可/拒否結果を組み立てる。"""
    output: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
        }
    }
    if reason:
        output["reason"] = reason
        output["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return output


def path_is_under(path: Path, directory: Path) -> bool:
    """path が directory 以下にあるかを、解決済みパスで判定する。"""
    return path.resolve().is_relative_to(directory.resolve())


def tool_file_path(tool_input: dict[str, Any]) -> str | None:
    """Write/Edit/MultiEdit 系ツール入力から対象ファイルパスを取り出す。"""
    file_path = tool_input.get("file_path")
    if isinstance(file_path, str) and file_path.strip():
        return file_path
    return None


def make_storage_write_guard(web_data_dir: Path):
    """LLM の変更を web_data_dir 以下に制限する PreToolUse hook を返す。"""

    async def guard(
        hook_input: dict[str, Any],
        tool_use_id: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        tool_name = hook_input.get("tool_name")
        if tool_name == "Bash":
            return hook_permission(
                "deny",
                "Bash は任意のファイル変更ができるため Sawagani では使用できません。",
            )
        if tool_name not in WRITE_TOOL_NAMES:
            return hook_permission("allow")

        file_path = tool_file_path(hook_input.get("tool_input", {}))
        if file_path is None:
            return hook_permission("deny", f"{tool_name} の対象ファイルを確認できません。")

        target_path = Path(file_path)
        if not target_path.is_absolute():
            target_path = settings.data_dir() / target_path

        if path_is_under(target_path, web_data_dir):
            return hook_permission("allow")

        return hook_permission(
            "deny",
            f"ファイル変更は {web_data_dir} 以下に限定されています。",
        )

    return guard


def memory_summary(text: str) -> str:
    """MEMORY.md に1行で保存できるよう、応答テキストの空白を正規化する。"""
    return " ".join(text.split())


def append_memory_entry(text: str) -> None:
    """LLM の作業報告を MEMORY.md に追記する。"""
    summary = memory_summary(text)
    if not summary:
        return

    memory_path = settings.data_dir() / settings.MEMORY_FILE
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

    needs_leading_newline = False
    if memory_path.exists() and memory_path.stat().st_size > 0:
        with memory_path.open("rb") as f:
            f.seek(-1, 2)
            needs_leading_newline = f.read(1) != b"\n"

    with memory_path.open("a", encoding="utf-8") as f:
        if needs_leading_newline:
            f.write("\n")
        f.write(f"- {timestamp} {summary}\n")


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
        append_memory_entry(text)


async def run_once() -> None:
    """1ティックだけ実行（テスト用）。"""
    async with ClaudeSDKClient(build_options()) as client:
        await tick(client)


async def sleep_until_next_tick(
    interval: int,
    stop_file: Path,
    check_interval: float = 1.0,
) -> bool:
    """次ティックまで待機し、待機中に STOP が作られたら True を返す。

    長い interval を一度に sleep すると STOP の検知が次回起床まで遅れるため、
    短い間隔で区切ってキルスイッチを確認する。
    """
    remaining = float(interval)
    while remaining > 0:
        if stop_file.exists():
            return True

        sleep_for = min(check_interval, remaining)
        await anyio.sleep(sleep_for)
        remaining -= sleep_for

        if stop_file.exists():
            return True

    return False


async def run_loop(interval: int, max_ticks: int) -> None:
    """一定間隔のハートビート・ループ。文脈を保つため client は1つを使い回す。"""
    interval = max(interval, settings.load_settings().min_interval_sec)
    stop_file = settings.stop_path()
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
                if await sleep_until_next_tick(interval, stop_file):
                    print(f"⏹ {stop_file.name} を検出したため停止します。")
                    return

    print(f"\n✅ 最大 {max_ticks} 回に達したため終了しました。")
