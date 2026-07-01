"""Sawagani のハートビート・エージェント本体（実行エンジンの責務）。

「一定間隔で起動し、状態ファイルを読んで作業を1つ実行する」ことだけを担う。
設定は settings モジュールから取得し、CLI（引数解析）には依存しない。
"""

from datetime import datetime
from itertools import count
from pathlib import Path
from collections.abc import Iterator
from typing import Any
import shlex

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    TextBlock,
)

from . import schedule, settings

WRITE_TOOL_NAMES = {"Write", "Edit", "MultiEdit"}
WRITE_GUARD_MATCHER = "Write|Edit|MultiEdit|Bash"
BASH_CONTROL_TOKENS = {";", "&&", "||", "|", ">", ">>", "<", "<<", "&"}


def build_options() -> ClaudeAgentOptions:
    """最小・セキュアな実行オプションを組み立てる。

    許可ツールやガード値は config.toml（無ければ組み込みデフォルト）から読む。
    """
    loaded_settings = settings.load_settings()
    web_data_dir = settings.web_data_dir(loaded_settings)
    web_data_dir.mkdir(parents=True, exist_ok=True)
    allowed_tools = list(loaded_settings.allowed_tools)
    allowed_bash_commands: list[str] = []
    if loaded_settings.downloads.allow_bash_downloads:
        allowed_bash_commands = loaded_settings.downloads.allowed_commands
        if "Bash" not in allowed_tools:
            allowed_tools.append("Bash")

    return ClaudeAgentOptions(
        cwd=str(settings.data_dir()),                # 状態ファイルのあるディレクトリを作業場所に
        allowed_tools=allowed_tools,  # 設定で許可されたツールのみ
        permission_mode="dontAsk",             # 許可外ツールは自動拒否
        system_prompt=settings.system_prompt(web_data_dir),
        max_turns=loaded_settings.max_turns_per_tick,  # 1ティックの上限
        add_dirs=[web_data_dir],
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher=WRITE_GUARD_MATCHER,
                    hooks=[
                        make_write_guard(
                            allowed_dirs=[web_data_dir],
                            allowed_files=[settings.schedule_path()],
                            allowed_bash_commands=allowed_bash_commands,
                        )
                    ],
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


def tool_bash_command(tool_input: dict[str, Any]) -> str | None:
    """Bash ツール入力からコマンド文字列を取り出す。"""
    command = tool_input.get("command")
    if isinstance(command, str) and command.strip():
        return command
    return None


def is_allowed_bash_download(command: str, allowed_commands: list[str]) -> bool:
    """Bash コマンドが許可された curl/wget ダウンロードかを判定する。"""
    if not allowed_commands:
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    if any(token in BASH_CONTROL_TOKENS for token in tokens):
        return False

    executable = Path(tokens[0]).name
    return executable in set(allowed_commands)


def make_write_guard(
    allowed_dirs: list[Path],
    allowed_files: list[Path],
    allowed_bash_commands: list[str] | None = None,
):
    """LLM の変更先を許可ファイルと許可ディレクトリ配下に制限する hook を返す。

    Bash は変更先を静的に保証できないため常に拒否する。Write/Edit/MultiEdit の
    相対パスは、状態ファイルと同じく ``settings.data_dir()`` 基準で解決する。
    """
    resolved_dirs = [directory.resolve() for directory in allowed_dirs]
    resolved_files = [file.resolve() for file in allowed_files]
    allowed_bash_commands = allowed_bash_commands or []

    async def guard(
        hook_input: dict[str, Any],
        tool_use_id: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        tool_name = hook_input.get("tool_name")
        if tool_name == "Bash":
            command = tool_bash_command(hook_input.get("tool_input", {}))
            if command is not None and is_allowed_bash_download(command, allowed_bash_commands):
                return hook_permission("allow")
            return hook_permission(
                "deny",
                "Bash は任意のファイル変更ができるため Sawagani では原則使用できません。",
            )
        if tool_name not in WRITE_TOOL_NAMES:
            return hook_permission("allow")

        file_path = tool_file_path(hook_input.get("tool_input", {}))
        if file_path is None:
            return hook_permission("deny", f"{tool_name} の対象ファイルを確認できません。")

        target_path = Path(file_path)
        if not target_path.is_absolute():
            target_path = settings.data_dir() / target_path

        resolved_target = target_path.resolve()
        if any(resolved_target == allowed_file for allowed_file in resolved_files):
            return hook_permission("allow")
        if any(path_is_under(resolved_target, allowed_dir) for allowed_dir in resolved_dirs):
            return hook_permission("allow")

        return hook_permission(
            "deny",
            "ファイル変更は許可された設定ファイル・タスクファイル・保存先ディレクトリに限定されています。",
        )

    return guard


def make_storage_write_guard(web_data_dir: Path, allowed_bash_commands: list[str] | None = None):
    """LLM の変更を web_data_dir 以下に制限する PreToolUse hook を返す。"""
    return make_write_guard(
        allowed_dirs=[web_data_dir],
        allowed_files=[],
        allowed_bash_commands=allowed_bash_commands,
    )


def build_chat_options() -> ClaudeAgentOptions:
    """Discord 会話モード用の Claude Agent SDK オプションを組み立てる。"""
    loaded_settings = settings.load_settings()
    web_data_dir = settings.web_data_dir(loaded_settings)
    web_data_dir.mkdir(parents=True, exist_ok=True)
    config_path = settings.data_dir() / settings.CONFIG_FILE
    tasks_path = settings.data_dir() / settings.TASKS_FILE
    schedule_path = settings.schedule_path()
    web_tools = [
        tool
        for tool in loaded_settings.allowed_tools
        if tool in {"WebSearch", "WebFetch"}
    ]
    allowed_tools = ["Read", "Write", "Edit", *web_tools]
    allowed_bash_commands: list[str] = []
    if loaded_settings.downloads.allow_bash_downloads:
        allowed_bash_commands = loaded_settings.downloads.allowed_commands
        allowed_tools.append("Bash")

    return ClaudeAgentOptions(
        cwd=str(settings.data_dir()),
        allowed_tools=allowed_tools,
        permission_mode="dontAsk",
        system_prompt=settings.chat_system_prompt(web_data_dir, config_path, tasks_path),
        max_turns=loaded_settings.max_turns_per_tick,
        add_dirs=[web_data_dir],
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher=WRITE_GUARD_MATCHER,
                    hooks=[
                        make_write_guard(
                            allowed_dirs=[web_data_dir],
                            allowed_files=[config_path, tasks_path, schedule_path],
                            allowed_bash_commands=allowed_bash_commands,
                        )
                    ],
                )
            ]
        },
    )


async def run_chat_turn(client: ClaudeSDKClient, user_text: str) -> str:
    """会話モードの1ターンを実行し、Assistant のテキスト応答を返す。"""
    await client.query(user_text)

    parts: list[str] = []
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)

    return "".join(parts).strip()


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
    if settings.stop_path().exists():
        print(f"⏸ {settings.STOP_FILE} を検出したためティックをスキップします。")
        return

    schedule.fire_due()
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
    if settings.stop_path().exists():
        print(f"⏸ {settings.STOP_FILE} を検出したためティックをスキップします。")
        return

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


def tick_range(max_ticks: int) -> Iterator[int]:
    """ティック番号を返す。max_ticks=0 は無制限ループを表す。"""
    if max_ticks == 0:
        return count(1)
    return iter(range(1, max_ticks + 1))


async def run_loop(interval: int, max_ticks: int) -> None:
    """一定間隔のハートビート・ループ。文脈を保つため client は1つを使い回す。"""
    interval = max(interval, settings.load_settings().min_interval_sec)
    stop_file = settings.stop_path()
    max_ticks_label = "無制限" if max_ticks == 0 else str(max_ticks)
    print(f"🫀 ハートビート開始: 間隔 {interval}秒 / 最大 {max_ticks_label} 回 "
          f"（{stop_file.name} ファイルで停止）\n")

    async with ClaudeSDKClient(build_options()) as client:
        for i in tick_range(max_ticks):
            if stop_file.exists():
                print(f"⏸ {stop_file.name} を検出中のため一時停止しています。")
            else:
                print(f"--- ティック {i}/{max_ticks_label} ---")
                await tick(client)

            if max_ticks == 0 or i < max_ticks:
                if await sleep_until_next_tick(interval, stop_file):
                    print(f"⏸ {stop_file.name} を検出中のため一時停止しています。")

    if max_ticks > 0:
        print(f"\n✅ 最大 {max_ticks} 回に達したため終了しました。")
