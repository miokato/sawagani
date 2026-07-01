"""Discord Bot から Sawagani を操作するための内部モジュール。"""

import asyncio
import importlib
import os
from dataclasses import dataclass
from typing import Any

from . import agent, daemon, settings, tasks

DISCORD_BOT_TOKEN_ENV = "SAWAGANI_DISCORD_BOT_TOKEN"


@dataclass
class ConversationState:
    """Discord チャンネルごとに保持する会話セッション。"""

    client: Any
    lock: asyncio.Lock


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


def is_conversation_authorized(
    discord_settings: settings.DiscordSettings,
    guild_id: int | None,
    channel_id: int | None,
    user_id: int,
    is_dm: bool,
) -> bool:
    """Discord 会話モードの実行が設定上許可されているか判定する。"""
    if not discord_settings.enabled or not discord_settings.conversation:
        return False
    if is_dm:
        return not discord_settings.allowed_user_ids or user_id in discord_settings.allowed_user_ids
    return is_authorized(discord_settings, guild_id, channel_id, user_id)


def strip_bot_mention(content: str, bot_user_id: int) -> str:
    """メッセージ先頭の Bot メンションを取り除いて本文を返す。"""
    text = content.strip()
    for mention in (f"<@{bot_user_id}>", f"<@!{bot_user_id}>"):
        if text.startswith(mention):
            return text[len(mention):].strip()
    return text


def chunk_message(text: str, limit: int = 2000) -> list[str]:
    """Discord の文字数上限に収まるよう、改行を優先してメッセージを分割する。"""
    if text == "":
        return [""]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]

        if current and len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line

    if current:
        chunks.append(current)
    return chunks or [text]


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

    # メンション/DM 宛ての本文は Message Content Intent なしで届くため、
    # 特権インテントを増やさず default のまま運用する。
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="sawagani!", intents=intents)
    group = app_commands.Group(name="sawagani", description="Sawagani を操作します")
    conversations: dict[int, ConversationState] = {}
    conversations_lock = asyncio.Lock()

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

    async def get_conversation(channel_id: int) -> ConversationState:
        """チャンネルごとの ClaudeSDKClient を遅延生成して返す。"""
        async with conversations_lock:
            state = conversations.get(channel_id)
            if state is not None:
                return state

            client = agent.ClaudeSDKClient(agent.build_chat_options())
            entered_client = await client.__aenter__()
            state = ConversationState(client=entered_client, lock=asyncio.Lock())
            conversations[channel_id] = state
            return state

    async def reset_conversation(channel_id: int) -> None:
        """該当チャンネルの会話文脈を破棄する。"""
        async with conversations_lock:
            state = conversations.pop(channel_id, None)
        if state is None:
            return
        async with state.lock:
            await state.client.__aexit__(None, None, None)

    @bot.event
    async def on_message(message: Any) -> None:
        """DM または Bot メンションを Sawagani 会話モードとして処理する。"""
        if getattr(message.author, "bot", False):
            return

        is_dm = message.guild is None
        bot_user = getattr(bot, "user", None)
        is_mentioned = bool(bot_user is not None and bot_user.mentioned_in(message))
        if not is_dm and not is_mentioned:
            return

        guild_id = None if is_dm else int(message.guild.id)
        channel_id = int(message.channel.id)
        user_id = int(message.author.id)
        if not is_conversation_authorized(discord_settings, guild_id, channel_id, user_id, is_dm):
            if is_dm:
                await message.channel.send("この Sawagani Bot と会話する権限がありません。")
            return

        bot_user_id = int(bot_user.id) if bot_user is not None else 0
        text = strip_bot_mention(message.content, bot_user_id)
        if text == "":
            await message.reply("はい、なんでしょう？")
            return
        if text == "リセット":
            await reset_conversation(channel_id)
            await message.reply("会話の文脈をリセットしました。")
            return

        async with message.channel.typing():
            state = await get_conversation(channel_id)
            async with state.lock:
                try:
                    reply = await agent.run_chat_turn(state.client, text)
                except Exception:
                    await message.reply("会話処理中にエラーが発生しました。ログを確認してください。")
                    raise

        if reply == "":
            reply = "応答が空でした。もう一度聞いてください。"
        for chunk in chunk_message(reply):
            await message.reply(chunk)

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
