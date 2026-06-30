"""Discord Bot から Sawagani を操作するための内部モジュール。"""

import importlib
import os
from typing import Any

from . import agent, daemon, settings, tasks

DISCORD_BOT_TOKEN_ENV = "SAWAGANI_DISCORD_BOT_TOKEN"


def bot_token() -> str:
    """Discord Bot Token を環境変数から読む。"""
    token = os.environ.get(DISCORD_BOT_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(f"{DISCORD_BOT_TOKEN_ENV} is not set")
    return token


def is_authorized(
    discord_settings: settings.DiscordSettings,
    guild_id: int | None,
    channel_id: int | None,
    user_id: int,
) -> bool:
    """Discord コマンドの実行が設定上許可されているか判定する。"""
    if not discord_settings.enabled:
        return False
    if discord_settings.guild_id is not None and guild_id != discord_settings.guild_id:
        return False
    if discord_settings.channel_id is not None and channel_id != discord_settings.channel_id:
        return False
    if discord_settings.allowed_user_ids and user_id not in discord_settings.allowed_user_ids:
        return False
    return True


def handle_task(text: str) -> str:
    """Discord task コマンド: tasks.md に依頼を追記する。"""
    path = tasks.append_task(text, source="discord")
    return f"{path.name} に追加しました。"


def format_status(result: daemon.StatusResult) -> str:
    """Discord status コマンド用に状態を短く整形する。"""
    if result.running:
        return f"running pid={result.pid}"
    return result.message


async def handle_tick() -> str:
    """Discord tick コマンド: 1回だけ Sawagani を実行する。"""
    await agent.run_once()
    return "tick を実行しました。"


async def reject_if_unauthorized(interaction: Any, discord_settings: settings.DiscordSettings) -> bool:
    """未許可の Discord interaction なら応答して True を返す。"""
    user_id = int(interaction.user.id)
    guild_id = interaction.guild_id
    channel_id = interaction.channel_id
    if is_authorized(discord_settings, guild_id, channel_id, user_id):
        return False

    await interaction.response.send_message("この Sawagani Bot を操作する権限がありません。", ephemeral=True)
    return True


def create_bot(discord_settings: settings.DiscordSettings) -> Any:
    """discord.py の Bot を構築する。"""
    discord = importlib.import_module("discord")
    commands = importlib.import_module("discord.ext.commands")
    app_commands = getattr(discord, "app_commands")

    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="sawagani!", intents=intents)
    group = app_commands.Group(name="sawagani", description="Sawagani を操作します")

    @group.command(name="status", description="Sawagani の状態を表示します")
    async def status_command(interaction: Any) -> None:
        if await reject_if_unauthorized(interaction, discord_settings):
            return
        await interaction.response.send_message(format_status(daemon.status()), ephemeral=True)

    @group.command(name="task", description="Sawagani の tasks.md に依頼を追加します")
    async def task_command(interaction: Any, text: str) -> None:
        if await reject_if_unauthorized(interaction, discord_settings):
            return
        await interaction.response.send_message(handle_task(text), ephemeral=True)

    @group.command(name="tick", description="Sawagani を1回だけ実行します")
    async def tick_command(interaction: Any) -> None:
        if await reject_if_unauthorized(interaction, discord_settings):
            return
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(await handle_tick(), ephemeral=True)

    guild = discord.Object(id=discord_settings.guild_id) if discord_settings.guild_id else None
    bot.tree.add_command(group, guild=guild)

    async def setup_hook() -> None:
        await bot.tree.sync(guild=guild)

    # discord.py はインスタンス属性の setup_hook を束縛せず await self.setup_hook() で
    # 呼ぶため、無引数関数を動的に差し込む。属性の型（self を取るメソッド）とは一致しない
    # ので、型不一致を避けるため setattr で代入する。
    setattr(bot, "setup_hook", setup_hook)
    return bot


def run_from_env() -> None:
    """環境変数と config.toml から Discord Bot を起動する。"""
    loaded_settings = settings.load_settings()
    if not loaded_settings.discord.enabled:
        raise RuntimeError("Discord integration is disabled in config.toml")
    bot = create_bot(loaded_settings.discord)
    bot.run(bot_token())
