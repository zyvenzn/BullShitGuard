"""Rate-limited personality replies. Registered LAST so commands win."""
from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from .. import keyboards as kb
from .. import texts
from ..runtime import Runtime

router = Router(name="fun")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text, ~F.text.startswith("/"))

CHAT_COOLDOWN = 45   # seconds between any two personality replies in the group
TRIGGER_COOLDOWN = 180


@router.message()
async def personality(message: Message, rt: Runtime) -> None:
    text = message.text or ""
    now = time.time()
    chat_id = message.chat.id

    if texts.CA_QUESTION_RE.match(text):
        if not rt.cooldowns.hit(("ca-q", chat_id), 60, now):
            return
        ca = await rt.get_ca()
        await message.reply(texts.build_ca(ca), reply_markup=kb.ca_menu(ca))
        return

    picked = texts.pick_reply(text)
    if not picked:
        return
    key, reply = picked
    if not rt.cooldowns.hit(("fun-chat", chat_id), CHAT_COOLDOWN, now):
        return
    if not rt.cooldowns.hit(("fun", chat_id, key), TRIGGER_COOLDOWN, now):
        return
    await message.reply(reply)
