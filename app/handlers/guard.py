"""Automatic moderation: scam scoring, new-member probation, link limits, flood.

Implemented as an *outer middleware* so it sees every group message
(including ones that look like commands) before any handler runs.
Admins are never filtered.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message

from .. import texts
from ..runtime import Runtime, utc_day
from ..scam import extract_links, looks_like_admin, scan_message, verdict
from ..services import modactions
from ..spam import mute_minutes_for
from ..tg import delete_later, safe

log = logging.getLogger("bullshit.guard")

GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)
TELEGRAM_SYSTEM_IDS = {777000, 1087968824}  # channel auto-forward, anonymous admin


def message_urls(message: Message) -> list[str]:
    """Hidden URLs behind text-link entities (a classic phishing trick)."""
    urls: list[str] = []
    for ent in list(message.entities or []) + list(message.caption_entities or []):
        if ent.type == "text_link" and ent.url:
            urls.append(ent.url)
    return urls


def has_restricted_content(message: Message) -> bool:
    """Forwards and documents are blocked during probation/lockdown."""
    return bool(getattr(message, "forward_origin", None) or message.document)


class GuardMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
                       event: Message, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message) or event.chat.type not in GROUPS or event.from_user is None:
            return await handler(event, data)
        user = event.from_user
        if user.is_bot or user.id in TELEGRAM_SYSTEM_IDS or event.sender_chat is not None:
            return await handler(event, data)

        rt: Runtime = data["rt"]
        bot = data["bot"]
        chat_id = event.chat.id
        now = time.time()

        if await rt.is_admin(bot, chat_id, user.id):
            return await handler(event, data)

        joined = await rt.db.record_message(user.id, user.username, user.first_name, int(now), utc_day(now))
        in_probation = joined is not None and now - joined < rt.thr["probation_hours"] * 3600

        text = event.text or event.caption or ""
        urls = message_urls(event)

        # ---- 1. scam scoring --------------------------------------------------
        impersonating = looks_like_admin([user.first_name, user.full_name, user.username or ""],
                                         await rt.admin_names(bot, chat_id))
        scan = scan_message(text, await rt.allowlist(), extra_urls=urls, impersonating_admin=impersonating)
        s = rt.settings
        delete_at = max(s.scam_delete_score - (2 if rt.strict else 0), 1)
        action = verdict(scan.score, delete_at=delete_at, warn_at=min(s.scam_warn_score, delete_at), ban_at=s.scam_ban_score)
        # unverified accounts with any bait get less slack
        if action == "warn" and in_probation:
            action = "delete"

        if action in ("delete", "ban"):
            log.warning("scam suspected", extra={"user_id": user.id, "score": scan.score, "reasons": scan.reasons})
            await safe(lambda: event.delete(), what="delete-scam")
            if action == "ban":
                await modactions.ban(rt, bot, chat_id, user.id, admin_id=None, reason="scam: " + ",".join(scan.reasons)[:200])
            else:
                await modactions.warn(rt, bot, chat_id, user.id, admin_id=None, reason="scam: " + ",".join(scan.reasons)[:200])
            if rt.cooldowns.hit(("scam-alert", chat_id), 20, now):
                sent = await safe(lambda: bot.send_message(chat_id, texts.SCAM_ALERT), what="scam-alert")
                if sent:
                    delete_later(bot, chat_id, sent.message_id, 30)
            return None
        if action == "warn":
            log.info("suspicious message", extra={"user_id": user.id, "score": scan.score, "reasons": scan.reasons})

        # ---- 2. probation / lockdown: no links, forwards or documents ---------
        links = scan.links or extract_links(text)
        if (in_probation or rt.strict) and (links or urls or has_restricted_content(event)):
            await safe(lambda: event.delete(), what="delete-probation")
            if rt.cooldowns.hit(("probation-note", chat_id, user.id), 300, now):
                note = await safe(lambda: bot.send_message(
                    chat_id, "🐂 New here? Links, forwards and files unlock after your first day. Memes and words are fine."),
                    what="probation-note")
                if note:
                    delete_later(bot, chat_id, note.message_id, 15)
            return None

        # ---- 3. too many links ------------------------------------------------
        if len(links) + len(urls) > rt.thr["max_links"]:
            await safe(lambda: event.delete(), what="delete-links")
            await modactions.record(rt, bot, admin_id=None, target_id=user.id, action="too_many_links", notify=False)
            return None

        # ---- 4. flood / repeat ------------------------------------------------
        kind = rt.tracker.check(chat_id, user.id, text, now)
        if kind:
            await safe(lambda: event.delete(), what="delete-flood")
            strike = rt.tracker.strike(chat_id, user.id, now)
            minutes = mute_minutes_for(strike, rt.thr["mute_minutes"])
            await modactions.mute(rt, bot, chat_id, user.id, minutes * 60, admin_id=None, reason=f"{kind} (strike {strike})")
            if strike >= 3:
                await modactions.warn(rt, bot, chat_id, user.id, admin_id=None, reason=f"repeated {kind}")
            if rt.cooldowns.hit(("flood-note", chat_id, user.id), 60, now):
                note = await safe(lambda: bot.send_message(chat_id, f"🤐 {user.first_name} muted for {minutes}m. Slow down, bull."),
                                  what="flood-note")
                if note:
                    delete_later(bot, chat_id, note.message_id, 20)
            return None

        return await handler(event, data)
