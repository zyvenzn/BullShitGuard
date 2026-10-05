"""Admin / owner configuration commands."""
from __future__ import annotations

import logging
import secrets
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import LinkPreviewOptions, CallbackQuery, ChatPermissions, Message

from .. import keyboards as kb
from .. import texts
from ..config import THRESHOLDS
from ..runtime import Runtime
from ..services import modactions
from ..tg import safe
from ..utils import esc, parse_announcement, strip_command, truncate
from ..validators import is_https_url, is_solana_address

log = logging.getLogger("bullshit.admin")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
router = Router(name="admin")

GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)
LINK_KEYS = ("x", "website", "buy", "telegram")


async def require_admin(message: Message, bot: Bot, rt: Runtime) -> bool:
    uid = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    # in private chat only configured admins count; in a group, real group admins count too
    ok = rt.settings.privileged_ids and uid in rt.settings.privileged_ids
    if not ok and message.chat.type in GROUPS:
        ok = await rt.is_admin(bot, chat_id, uid)
    if not ok:
        await message.reply("Permission denied.")
    return bool(ok)


async def require_owner(message: Message, rt: Runtime) -> bool:
    if message.from_user and rt.is_owner(message.from_user.id):
        return True
    await message.reply("Permission denied.")
    return False


# ------------------------------------------------------------------ info
@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot, rt: Runtime) -> None:
    if await require_admin(message, bot, rt):
        await message.reply(texts.ADMIN_HELP)


@router.message(Command("settings"))
async def cmd_settings(message: Message, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    ca = await rt.get_ca()
    links = await rt.get_links()
    custom_w = bool(await rt.db.get_setting("welcome"))
    custom_r = bool(await rt.db.get_setting("rules"))
    lines = [
        "⚙️ <b>SETTINGS</b>",
        f"CA: {'set' if ca else 'not set (COMING SOON)'}",
        "Links: " + ", ".join(f"{k}={'set' if links[k] else '—'}" for k in LINK_KEYS),
        f"Welcome: {'custom' if custom_w else 'default'} · Rules: {'custom' if custom_r else 'default'}",
        f"Verification: {'on' if rt.settings.verify_enabled else 'off'}",
        f"Lockdown (raid mode): {'ON' if rt.strict else 'off'}",
        "",
        "<b>Thresholds</b>",
        *[f"{k} = {v}" for k, v in rt.thr.items()],
    ]
    await message.reply("\n".join(lines))


# ------------------------------------------------------------------ welcome / rules
async def _save_text(message: Message, bot: Bot, rt: Runtime, key: str, label: str, preview_sample: bool) -> None:
    if not await require_admin(message, bot, rt):
        return
    body = strip_command(message.html_text or message.text)
    if not body:
        await message.reply(f"Usage: /set{label} &lt;text&gt; (Telegram HTML supported) or /set{label} reset")
        return
    if body.lower() == "reset":
        await rt.db.del_setting(key)
        await message.reply(f"{label.capitalize()} reset to default.")
        return
    if len(body) > 3500:
        await message.reply("Too long (max 3500 characters).")
        return
    preview = body
    if preview_sample:
        preview = texts.render_welcome(body, first_name="Anon", username="anon", user_id=message.from_user.id,
                                       group_name=message.chat.title or "BULLSHIT")
    sent = await safe(lambda: message.reply("<b>Preview:</b>\n\n" + preview), what="preview")
    if sent is None:
        await message.reply("Telegram rejected that formatting (invalid HTML). Not saved.")
        return
    await rt.db.set_setting(key, body)
    await modactions.record(rt, bot, admin_id=message.from_user.id, target_id=0, action=f"set_{key}")
    await message.reply("Saved. ✅")


@router.message(Command("setwelcome"))
async def cmd_setwelcome(message: Message, bot: Bot, rt: Runtime) -> None:
    await _save_text(message, bot, rt, "welcome", "welcome", True)


@router.message(Command("setrules"))
async def cmd_setrules(message: Message, bot: Bot, rt: Runtime) -> None:
    await _save_text(message, bot, rt, "rules", "rules", False)


# ------------------------------------------------------------------ CA (owner, two-step)
@router.message(Command("setca"))
async def cmd_setca(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_owner(message, rt):
        return
    arg = (command.args or "").strip()
    if arg.lower() == "clear":
        await rt.db.del_setting("ca")
        await modactions.record(rt, bot, admin_id=message.from_user.id, target_id=0, action="clear_ca")
        await message.reply("CA override cleared. Using the BULLSHIT_CA env value (or COMING SOON).")
        return
    if not is_solana_address(arg):
        await message.reply("That doesn't look like a Solana address (base58, 32 bytes). Usage: /setca &lt;address&gt; | clear")
        return
    # purge expired
    now = time.time()
    for t in [t for t, (_, _, exp) in rt.pending_ca.items() if exp < now]:
        rt.pending_ca.pop(t, None)
    token = secrets.token_hex(6)
    rt.pending_ca[token] = (arg, message.from_user.id, now + 120)
    await message.reply(
        f"⚠️ Set the <b>official</b> CA to:\n<code>{esc(arg)}</code>\n\nCheck it character by character. Expires in 2 min.",
        reply_markup=kb.confirm_menu("setca", token),
    )


@router.callback_query(F.data.startswith("setca:"))
async def cb_setca(cb: CallbackQuery, bot: Bot, rt: Runtime) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 3 or cb.message is None:
        await cb.answer()
        return
    _, decision, token = parts
    entry = rt.pending_ca.get(token)
    if not entry or entry[1] != cb.from_user.id or entry[2] < time.time() or not rt.is_owner(cb.from_user.id):
        await cb.answer("Expired or not yours.", show_alert=True)
        return
    rt.pending_ca.pop(token, None)
    if decision != "yes":
        await safe(lambda: cb.message.edit_text("Cancelled."), what="edit")
        await cb.answer()
        return
    await rt.db.set_setting("ca", entry[0])
    await modactions.record(rt, bot, admin_id=cb.from_user.id, target_id=0, action="set_ca", reason=entry[0])
    await safe(lambda: cb.message.edit_text(f"✅ Official CA set:\n<code>{esc(entry[0])}</code>"), what="edit")
    await cb.answer("Saved")


# ------------------------------------------------------------------ links (owner)
@router.message(Command("setlinks"))
async def cmd_setlinks(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_owner(message, rt):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or parts[0].lower() not in LINK_KEYS:
        await message.reply("Usage: /setlinks &lt;x|website|buy|telegram&gt; &lt;https://url | clear&gt;")
        return
    key, value = parts[0].lower(), parts[1]
    if value.lower() == "clear":
        await rt.db.del_setting(f"link:{key}")
        await message.reply(f"{key} link cleared.")
    elif is_https_url(value):
        await rt.db.set_setting(f"link:{key}", value)
        await modactions.record(rt, bot, admin_id=message.from_user.id, target_id=0, action=f"set_link_{key}", reason=value)
        await message.reply(f"{key} link saved. ✅")
    else:
        await message.reply("Only valid https:// URLs are accepted.")


# ------------------------------------------------------------------ thresholds
@router.message(Command("setthreshold"))
async def cmd_setthreshold(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        names = "\n".join(f"{k} ({lo}–{hi}) = {rt.thr[k]}" for k, (lo, hi) in THRESHOLDS.items())
        await message.reply(f"Usage: /setthreshold &lt;name&gt; &lt;number&gt;\n\n{names}")
        return
    err = await rt.set_threshold(parts[0].lower(), int(parts[1]))
    if err:
        await message.reply(err)
        return
    await modactions.record(rt, bot, admin_id=message.from_user.id, target_id=0, action="set_threshold",
                            reason=f"{parts[0]}={parts[1]}")
    await message.reply(f"{parts[0].lower()} = {int(parts[1])} ✅")


# ------------------------------------------------------------------ announce
@router.message(Command("announce"))
async def cmd_announce(message: Message, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    if rt.settings.group_id is None:
        await message.reply("Set GROUP_ID in the environment first.")
        return
    raw = strip_command(message.html_text or message.caption)
    body, buttons = parse_announcement(raw)
    photo = None
    if message.photo:
        photo = message.photo[-1].file_id
    elif message.reply_to_message and message.reply_to_message.photo:
        photo = message.reply_to_message.photo[-1].file_id
    if not body and not photo:
        await message.reply("Usage: /announce &lt;text&gt; (attach or reply to a photo for an image)\n"
                            "Buttons: one per line as [Label|https://url]")
        return
    header = "📢 <b>OFFICIAL BULLSHIT ANNOUNCEMENT</b>\n\n"
    text = header + body
    markup = kb.announce_buttons(buttons)
    if photo:
        if len(text) > 1024:
            await message.reply("Caption too long for a photo (max ~1000 chars).")
            return
        sent = await safe(lambda: bot.send_photo(rt.settings.group_id, photo, caption=text, reply_markup=markup), what="announce")
    else:
        sent = await safe(lambda: bot.send_message(rt.settings.group_id, truncate(text, 4000), reply_markup=markup,
                                                   link_preview_options=NO_PREVIEW), what="announce")
    if sent is None:
        await message.reply("Couldn't send (bad HTML, or the bot lacks rights in the group).")
        return
    await modactions.record(rt, bot, admin_id=message.from_user.id, target_id=0, action="announce")
    await message.reply("Sent. 📢")


# ------------------------------------------------------------------ lock / lockdown
@router.message(Command("lock"))
async def cmd_lock(message: Message, bot: Bot, rt: Runtime) -> None:
    if rt.settings.coexist_mode:
        return
    if not await require_admin(message, bot, rt) or message.chat.type not in GROUPS:
        return
    if not await rt.db.get_setting("prev_perms"):
        chat = await safe(lambda: bot.get_chat(message.chat.id), what="get_chat")
        if chat is not None and chat.permissions is not None:
            await rt.db.set_setting("prev_perms", chat.permissions.model_dump_json(exclude_none=True))
    ok = await safe(lambda: bot.set_chat_permissions(message.chat.id, ChatPermissions(can_send_messages=False)), what="lock")
    if ok:
        await rt.set_strict(True)
        await modactions.record(rt, bot, admin_id=message.from_user.id, target_id=0, action="lock")
        await message.answer("🔒 Chat locked. The herd sleeps.")
    else:
        await message.reply("Couldn't lock (does the bot have 'restrict members' rights?).")


@router.message(Command("unlock"))
async def cmd_unlock(message: Message, bot: Bot, rt: Runtime) -> None:
    if rt.settings.coexist_mode:
        return
    if not await require_admin(message, bot, rt) or message.chat.type not in GROUPS:
        return
    stored = await rt.db.get_setting("prev_perms")
    perms = ChatPermissions.model_validate_json(stored) if stored else await modactions.default_permissions(bot, message.chat.id)
    if not perms.can_send_messages:  # never "restore" to a locked state
        perms = perms.model_copy(update={"can_send_messages": True})
    ok = await safe(lambda: bot.set_chat_permissions(message.chat.id, perms), what="unlock")
    if ok:
        await rt.db.del_setting("prev_perms")
        await rt.set_strict(False)
        await modactions.record(rt, bot, admin_id=message.from_user.id, target_id=0, action="unlock")
        await message.answer("🔓 Chat unlocked. Back to the bullshit.")
    else:
        await message.reply("Couldn't unlock.")


@router.message(Command("lockdown"))
async def cmd_lockdown(message: Message, bot: Bot, rt: Runtime) -> None:
    """Raid mode: chat stays open, but non-admins can't post links/forwards/media."""
    if not await require_admin(message, bot, rt):
        return
    await rt.set_strict(not rt.strict)
    await modactions.record(rt, bot, admin_id=message.from_user.id, target_id=0,
                            action="lockdown_on" if rt.strict else "lockdown_off")
    await message.reply("🚨 Lockdown ON: no links/forwards/media from non-admins." if rt.strict else "Lockdown off.")
