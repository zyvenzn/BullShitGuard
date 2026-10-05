"""Entry point: python -m app.main"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeDefault, Message, CallbackQuery

from .config import ConfigError, Settings
from .db import Database
from .handlers import admin, common, events, fun, moderation
from .handlers.guard import GuardMiddleware
from .logging_setup import setup_logging
from .runtime import Runtime
from .spam import FloodTracker
from .tg import safe

log = logging.getLogger("bullshit.main")
HEARTBEAT = Path(os.environ.get("HEARTBEAT_FILE") or Path(tempfile.gettempdir()) / "bullshit.heartbeat")
GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)

PUBLIC_COMMANDS = [
    ("about", "what is BULLSHIT"), ("rules", "the rules"), ("ca", "contract address"),
    ("links", "official links"), ("stats", "community stats"), ("thesis", "the thesis"),
    ("wen", "wen"), ("gm", "gm"), ("gn", "gn"), ("bullshit", "bullshit"),
]
ADMIN_COMMANDS = [
    ("admin", "admin help"), ("settings", "current settings"), ("warn", "warn a user"),
    ("warnings", "show warnings"), ("mute", "mute a user"), ("unmute", "unmute"),
    ("ban", "ban"), ("unban", "unban"), ("kick", "kick"), ("purge", "bulk delete"),
    ("lock", "freeze chat"), ("unlock", "unfreeze chat"), ("lockdown", "raid mode"),
    ("announce", "official announcement"),
]


class ChatGate(BaseMiddleware):
    """Ignore groups other than GROUP_ID so the bot can't be used as a weapon elsewhere."""

    def __init__(self, group_id: int | None) -> None:
        self.group_id = group_id

    async def __call__(self, handler, event, data):
        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message is not None:
            chat = event.message.chat
        if chat is not None and chat.type in GROUPS and self.group_id is not None and chat.id != self.group_id:
            return None
        return await handler(event, data)


async def background(bot: Bot, rt: Runtime) -> None:
    tick = 0
    while True:
        try:
            try:
                HEARTBEAT.write_text(str(int(time.time())))
            except OSError:
                pass  # health file is best-effort (e.g. no writable /tmp on Termux)
            await events.sweep_unverified(bot, rt)
            tick += 1
            if tick % 20 == 0:  # ~10 min
                now = time.time()
                rt.tracker.cleanup(now)
                rt.cooldowns.cleanup(now)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let the loop die
            log.exception("background loop error")
        await asyncio.sleep(30)


async def run() -> None:
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        raise SystemExit(f"Config error: {e}")
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"), secrets=[settings.bot_token])

    db = Database(settings.database_path)
    await db.init()
    rt = Runtime(settings=settings, db=db, tracker=FloodTracker(
        settings.flood_messages, settings.flood_seconds, settings.repeat_limit))
    await rt.load()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    rt.bot_id = me.id

    dp = Dispatcher()
    dp["rt"] = rt
    gate = ChatGate(settings.group_id)
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    dp.message.outer_middleware(GuardMiddleware())
    routers = [common.router, admin.router, events.router, fun.router]
    if not settings.coexist_mode:  # in coexist mode another bot owns /ban /warn /mute ...
        routers.insert(2, moderation.router)
    for r in routers:
        dp.include_router(r)

    public = [c for c in PUBLIC_COMMANDS if not (settings.coexist_mode and c[0] == "rules")]
    await safe(lambda: bot.set_my_commands([BotCommand(command=c, description=d) for c, d in public],
                                           scope=BotCommandScopeDefault()), what="set_commands")
    public = [c for c in PUBLIC_COMMANDS if not (settings.coexist_mode and c[0] == "rules")]
    shared = {"warn", "warnings", "mute", "unmute", "ban", "unban", "kick", "purge", "lock", "unlock"}
    admin_cmds = [c for c in ADMIN_COMMANDS if not (settings.coexist_mode and c[0] in shared)]
    await safe(lambda: bot.set_my_commands(
        [BotCommand(command=c, description=d) for c, d in public + admin_cmds],
        scope=BotCommandScopeAllChatAdministrators()), what="set_admin_commands")

    if settings.group_id is None:
        log.warning("GROUP_ID is not set: the bot will moderate ANY group it is added to")
    log.info("bot started", extra={"username": me.username, "verify": settings.verify_enabled,
                                   "ca_configured": bool(settings.ca)})

    task = asyncio.create_task(background(bot, rt))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"])
    finally:
        task.cancel()
        await bot.session.close()
        db.close()
        log.info("bot stopped")


if __name__ == "__main__":
    asyncio.run(run())
