"""Public commands: everyone can use these."""
from __future__ import annotations

import random
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import LinkPreviewOptions, CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..runtime import Runtime, utc_day
from ..tg import safe

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
router = Router(name="common")

GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)


async def _cooling(message: Message, rt: Runtime, name: str, seconds: float = 4.0) -> bool:
    """True if this user used this command too recently (silently ignored in groups)."""
    if message.chat.type not in GROUPS or message.from_user is None:
        return False
    return not rt.cooldowns.hit(("cmd", message.chat.id, message.from_user.id, name), seconds, time.time())


async def render_rules(rt: Runtime) -> str:
    return (await rt.db.get_setting("rules")) or texts.RULES_DEFAULT


async def render_about(rt: Runtime) -> str:
    links = await rt.get_links()
    return texts.build_about(x=links["x"], website=links["website"], ca=await rt.get_ca())


# ------------------------------------------------------------------ commands
@router.message(Command("start", "help"))
async def cmd_start(message: Message, rt: Runtime) -> None:
    if await _cooling(message, rt, "start"):
        return
    links = await rt.get_links()
    await message.answer(texts.HELP_TEXT, reply_markup=kb.main_menu(links["x"]))


@router.message(Command("about"))
async def cmd_about(message: Message, rt: Runtime) -> None:
    if await _cooling(message, rt, "about"):
        return
    await message.answer(await render_about(rt), link_preview_options=NO_PREVIEW)


@router.message(Command("rules"))
async def cmd_rules(message: Message, rt: Runtime) -> None:
    if rt.settings.coexist_mode and message.chat.type in GROUPS:
        return  # another bot owns /rules in the group
    if await _cooling(message, rt, "rules"):
        return
    await message.answer(await render_rules(rt))


@router.message(Command("ca", "contract"))
async def cmd_ca(message: Message, rt: Runtime) -> None:
    if await _cooling(message, rt, "ca"):
        return
    ca = await rt.get_ca()
    await message.answer(texts.build_ca(ca), reply_markup=kb.ca_menu(ca))


@router.message(Command("links", "socials"))
async def cmd_links(message: Message, rt: Runtime) -> None:
    if await _cooling(message, rt, "links"):
        return
    markup = kb.links_menu(await rt.get_links())
    if markup is None:
        await message.answer("🐂 Official links: <b>COMING SOON</b>.\nIf someone DMs you a \"link\", it's a scam.")
        return
    await message.answer("🐂 <b>OFFICIAL LINKS</b>\nAnything else is not us.", reply_markup=markup)


@router.message(Command("stats"))
async def cmd_stats(message: Message, bot: Bot, rt: Runtime) -> None:
    if message.chat.type not in GROUPS:
        await message.answer("Stats only work inside the group. 🐂")
        return
    if await _cooling(message, rt, "stats", 15):
        return
    members = await safe(lambda: bot.get_chat_member_count(message.chat.id), what="member_count")
    s = await rt.db.get_stats(utc_day())
    await message.answer(
        texts.build_stats(members=members, messages=s["messages"], warnings=s["warnings"], new_members=s["new_members"])
    )


def _fun(name: str, replies: list[str]) -> None:
    @router.message(Command(name))
    async def _handler(message: Message, rt: Runtime) -> None:
        if await _cooling(message, rt, name, 10):
            return
        await message.answer(random.choice(replies))


_fun("gm", texts.GM_REPLIES)
_fun("gn", texts.GN_REPLIES)
_fun("thesis", texts.THESIS_REPLIES)
_fun("wen", texts.WEN_REPLIES)
_fun("bullshit", texts.BULLSHIT_REPLIES)


# ------------------------------------------------------------------ callbacks
@router.callback_query(F.data.startswith("menu:"))
async def on_menu(cb: CallbackQuery, bot: Bot, rt: Runtime) -> None:
    if cb.message is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    if not rt.cooldowns.hit(("menu", chat_id, cb.from_user.id), 2.0, time.time()):
        await cb.answer()
        return
    key = (cb.data or "").split(":", 1)[1]
    if key == "about":
        await bot.send_message(chat_id, await render_about(rt), link_preview_options=NO_PREVIEW)
    elif key == "rules":
        await bot.send_message(chat_id, await render_rules(rt))
    elif key == "ca":
        ca = await rt.get_ca()
        await bot.send_message(chat_id, texts.build_ca(ca), reply_markup=kb.ca_menu(ca))
    elif key == "links":
        markup = kb.links_menu(await rt.get_links())
        await bot.send_message(chat_id, "🐂 <b>OFFICIAL LINKS</b>" if markup else "🐂 Official links: <b>COMING SOON</b>.",
                               reply_markup=markup)
    await cb.answer()
