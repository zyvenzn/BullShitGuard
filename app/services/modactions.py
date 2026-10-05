"""Moderation actions shared by commands and automatic filters."""
from __future__ import annotations

import logging
import time
from typing import Any

from aiogram.types import ChatPermissions

from ..runtime import Runtime, utc_day
from ..tg import safe
from ..utils import esc, format_duration

log = logging.getLogger("bullshit.mod")

MUTED = ChatPermissions(can_send_messages=False)


async def record(rt: Runtime, bot: Any, *, admin_id: int | None, target_id: int, action: str,
                 reason: str | None = None, notify: bool = True) -> None:
    """Persist + log a moderation action; optionally post it to the log chat."""
    await rt.db.log_mod(int(time.time()), admin_id, target_id, action, reason)
    log.info("moderation", extra={"action": action, "admin_id": admin_id, "target": target_id, "reason": reason})
    if notify and rt.settings.log_chat_id:
        who = f"admin <code>{admin_id}</code>" if admin_id else "bot (auto)"
        await safe(
            lambda: bot.send_message(
                rt.settings.log_chat_id,
                f"🛡 <b>{esc(action)}</b> → <code>{target_id}</code>\nby {who}\n{esc(reason or '')}",
            ),
            what="log_chat",
        )


async def default_permissions(bot: Any, chat_id: int) -> ChatPermissions:
    chat = await safe(lambda: bot.get_chat(chat_id), what="get_chat")
    perms = getattr(chat, "permissions", None)
    if perms is not None:
        return perms
    return ChatPermissions(
        can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True,
        can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True,
        can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True,
    )


async def mute(rt: Runtime, bot: Any, chat_id: int, user_id: int, seconds: int, *, admin_id: int | None,
               reason: str | None = None) -> bool:
    until = int(time.time()) + seconds
    ok = await safe(lambda: bot.restrict_chat_member(chat_id, user_id, MUTED, until_date=until), what="mute")
    if ok:
        await rt.db.set_flags(user_id, muted=True)
        await record(rt, bot, admin_id=admin_id, target_id=user_id, action=f"mute {format_duration(seconds)}", reason=reason)
    return bool(ok)


async def unmute(rt: Runtime, bot: Any, chat_id: int, user_id: int, *, admin_id: int | None) -> bool:
    perms = await default_permissions(bot, chat_id)
    ok = await safe(lambda: bot.restrict_chat_member(chat_id, user_id, perms), what="unmute")
    if ok:
        await rt.db.set_flags(user_id, muted=False)
        await record(rt, bot, admin_id=admin_id, target_id=user_id, action="unmute")
    return bool(ok)


async def ban(rt: Runtime, bot: Any, chat_id: int, user_id: int, *, admin_id: int | None,
              reason: str | None = None) -> bool:
    ok = await safe(lambda: bot.ban_chat_member(chat_id, user_id, revoke_messages=True), what="ban")
    if ok:
        await rt.db.set_flags(user_id, banned=True)
        await record(rt, bot, admin_id=admin_id, target_id=user_id, action="ban", reason=reason)
    return bool(ok)


async def unban(rt: Runtime, bot: Any, chat_id: int, user_id: int, *, admin_id: int | None) -> bool:
    ok = await safe(lambda: bot.unban_chat_member(chat_id, user_id, only_if_banned=True), what="unban")
    if ok:
        await rt.db.set_flags(user_id, banned=False)
        await record(rt, bot, admin_id=admin_id, target_id=user_id, action="unban")
    return bool(ok)


async def kick(rt: Runtime, bot: Any, chat_id: int, user_id: int, *, admin_id: int | None,
               reason: str | None = None) -> bool:
    ok = await safe(lambda: bot.ban_chat_member(chat_id, user_id), what="kick")
    if ok:
        await safe(lambda: bot.unban_chat_member(chat_id, user_id, only_if_banned=True), what="kick-unban")
        await record(rt, bot, admin_id=admin_id, target_id=user_id, action="kick", reason=reason)
    return bool(ok)


async def warn(rt: Runtime, bot: Any, chat_id: int, user_id: int, *, admin_id: int | None,
               reason: str | None = None) -> tuple[int, str]:
    """Add a warning and apply thresholds. Returns (count, outcome) where
    outcome is 'warned', 'muted' or 'banned'."""
    count = await rt.db.add_warning(user_id, utc_day())
    await record(rt, bot, admin_id=admin_id, target_id=user_id, action=f"warn #{count}", reason=reason)
    if count >= rt.thr["warn_ban_at"]:
        await ban(rt, bot, chat_id, user_id, admin_id=admin_id, reason=f"{count} warnings")
        return count, "banned"
    if count >= rt.thr["warn_mute_at"]:
        await mute(rt, bot, chat_id, user_id, 3600, admin_id=admin_id, reason=f"{count} warnings")
        return count, "muted"
    return count, "warned"
