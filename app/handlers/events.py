"""Joins, verification, service-message cleanup."""
from __future__ import annotations

import logging
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from .. import keyboards as kb
from .. import texts
from ..runtime import Runtime, utc_day
from ..scam import looks_like_admin
from ..services import modactions
from ..tg import safe

log = logging.getLogger("bullshit.events")
router = Router(name="events")

GROUPS = {ChatType.GROUP, ChatType.SUPERGROUP}


@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION), F.chat.type.in_(GROUPS))
async def on_join(event: ChatMemberUpdated, bot: Bot, rt: Runtime) -> None:
    user = event.new_chat_member.user
    chat = event.chat
    now = int(time.time())

    if user.id == rt.bot_id:
        return

    # 1. Bots added by non-admins are removed.
    if user.is_bot:
        adder = event.from_user.id if event.from_user else 0
        if adder != user.id and not await rt.is_admin(bot, chat.id, adder):
            await modactions.ban(rt, bot, chat.id, user.id, admin_id=None, reason="bot added by non-admin")
        return

    await rt.db.upsert_user(user.id, user.username, user.first_name, now, joined=True)
    await rt.db.bump(utc_day(), "new_members")
    log.info("member joined", extra={"user_id": user.id, "chat_id": chat.id})

    # 2. Impersonation check: flag only (verification still applies).
    names = [user.first_name, user.full_name, user.username or ""]
    if looks_like_admin(names, await rt.admin_names(bot, chat.id)):
        await modactions.record(rt, bot, admin_id=None, target_id=user.id, action="impersonation_suspect",
                                reason="name resembles an admin")

    template = (await rt.db.get_setting("welcome")) or texts.WELCOME_DEFAULT
    text = texts.render_welcome(template, first_name=user.first_name, username=user.username,
                                user_id=user.id, group_name=chat.title or "BULLSHIT")

    if not rt.settings.verify_enabled:
        sent = await safe(lambda: bot.send_message(chat.id, text), what="welcome")
        if sent is None:  # custom HTML may be broken: fall back to default
            await safe(lambda: bot.send_message(chat.id, texts.render_welcome(
                texts.WELCOME_DEFAULT, first_name=user.first_name, username=user.username,
                user_id=user.id, group_name=chat.title or "BULLSHIT")), what="welcome-default")
        return

    # 3. Verification: mute until they press the button.
    restricted = await safe(lambda: bot.restrict_chat_member(chat.id, user.id, modactions.MUTED), what="restrict-new")
    timeout = rt.thr["verify_timeout_seconds"]
    prompt = texts.VERIFY_PROMPT.format(minutes=max(1, round(timeout / 60)))
    sent = await safe(lambda: bot.send_message(chat.id, text + prompt, reply_markup=kb.verify_menu(user.id)), what="welcome")
    if sent is None:
        sent = await safe(lambda: bot.send_message(
            chat.id,
            texts.render_welcome(texts.WELCOME_DEFAULT, first_name=user.first_name, username=user.username,
                                 user_id=user.id, group_name=chat.title or "BULLSHIT") + prompt,
            reply_markup=kb.verify_menu(user.id)), what="welcome-default")
    if restricted is not None:
        await rt.db.add_pending(chat.id, user.id, sent.message_id if sent else None, now + timeout)


@router.callback_query(F.data.startswith("verify:"))
async def on_verify(cb: CallbackQuery, bot: Bot, rt: Runtime) -> None:
    if cb.message is None:
        await cb.answer()
        return
    try:
        target = int((cb.data or "").split(":", 1)[1])
    except (ValueError, IndexError):
        await cb.answer()
        return
    if cb.from_user.id != target:
        await cb.answer("This button isn't for you. 🐂", show_alert=True)
        return
    chat_id = cb.message.chat.id
    pending = await rt.db.pop_pending(chat_id, target)
    perms = await modactions.default_permissions(bot, chat_id)
    ok = await safe(lambda: bot.restrict_chat_member(chat_id, target, perms), what="verify-unrestrict")
    if ok is None and pending is not None:
        # keep them pending so the sweeper/retry still works
        await rt.db.add_pending(chat_id, target, pending.get("message_id"), pending["deadline"])
        await cb.answer("Something broke. Try again.", show_alert=True)
        return
    await cb.answer("Verified. Welcome to the herd 🐂")
    await safe(lambda: bot.delete_message(chat_id, cb.message.message_id), what="delete-welcome")


async def sweep_unverified(bot: Bot, rt: Runtime) -> None:
    """Kick members who never pressed the verify button. Called every ~30s."""
    for row in await rt.db.due_pending(int(time.time())):
        await rt.db.pop_pending(row["chat_id"], row["user_id"])
        await modactions.kick(rt, bot, row["chat_id"], row["user_id"], admin_id=None, reason="did not verify in time")
        if row.get("message_id"):
            await safe(lambda r=row: bot.delete_message(r["chat_id"], r["message_id"]), what="delete-welcome")


# Remove "X joined" / "X left" service messages to keep the chat clean.
@router.message(F.chat.type.in_(GROUPS), F.new_chat_members | F.left_chat_member)
async def drop_service(message: Message, bot: Bot) -> None:
    await safe(lambda: message.delete(), what="delete-service")
