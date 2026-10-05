"""Admin moderation commands (group only)."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..runtime import Runtime
from ..services import modactions
from ..tg import safe
from ..utils import esc, format_duration, parse_duration, parse_target_token, split_target_args
from .admin import require_admin

router = Router(name="moderation")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


async def resolve_target(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> tuple[int | None, str, str]:
    """Return (user_id, label, rest). user_id is None (and a reply was sent) on failure."""
    reply = message.reply_to_message
    has_reply = bool(reply and reply.from_user)
    token, rest = split_target_args(command.args, has_reply)

    if has_reply:
        u = reply.from_user
        target_id, label = u.id, (f"@{u.username}" if u.username else u.first_name)
    else:
        uid, uname = parse_target_token(token)
        if uid is not None:
            target_id, label = uid, str(uid)
        elif uname:
            row = await rt.db.find_user_by_username(uname)
            if not row:
                await message.reply(f"I don't know @{esc(uname)} yet. Reply to one of their messages, or use their numeric ID.")
                return None, "", rest
            target_id, label = row["user_id"], f"@{uname}"
        else:
            await message.reply("Reply to a user's message, or pass @username / user ID.")
            return None, "", rest

    if target_id == rt.bot_id:
        await message.reply("Nice try. 🐂")
        return None, "", rest
    if await rt.is_admin(bot, message.chat.id, target_id):
        await message.reply("I don't moderate admins.")
        return None, "", rest
    return target_id, label, rest


def _admin_id(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    uid, label, reason = await resolve_target(message, command, bot, rt)
    if uid is None:
        return
    ok = await modactions.ban(rt, bot, message.chat.id, uid, admin_id=_admin_id(message), reason=reason or None)
    await message.reply(f"🔨 Banned {esc(label)}." if ok else "Couldn't ban (missing rights or user not found).")


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    uid, label, _ = await resolve_target(message, command, bot, rt)
    if uid is None:
        return
    ok = await modactions.unban(rt, bot, message.chat.id, uid, admin_id=_admin_id(message))
    await message.reply(f"✅ Unbanned {esc(label)}." if ok else "Couldn't unban.")


@router.message(Command("kick"))
async def cmd_kick(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    uid, label, reason = await resolve_target(message, command, bot, rt)
    if uid is None:
        return
    ok = await modactions.kick(rt, bot, message.chat.id, uid, admin_id=_admin_id(message), reason=reason or None)
    await message.reply(f"👢 Kicked {esc(label)}." if ok else "Couldn't kick.")


@router.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    uid, label, rest = await resolve_target(message, command, bot, rt)
    if uid is None:
        return
    seconds = rt.thr["mute_minutes"] * 60
    reason = rest
    first, _, tail = rest.partition(" ")
    parsed = parse_duration(first) if first else None
    if parsed:
        seconds, reason = parsed, tail.strip()
    ok = await modactions.mute(rt, bot, message.chat.id, uid, seconds, admin_id=_admin_id(message), reason=reason or None)
    await message.reply(f"🤐 Muted {esc(label)} for {format_duration(seconds)}." if ok else "Couldn't mute.")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    uid, label, _ = await resolve_target(message, command, bot, rt)
    if uid is None:
        return
    ok = await modactions.unmute(rt, bot, message.chat.id, uid, admin_id=_admin_id(message))
    await message.reply(f"🔊 Unmuted {esc(label)}." if ok else "Couldn't unmute.")


@router.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    uid, label, reason = await resolve_target(message, command, bot, rt)
    if uid is None:
        return
    count, outcome = await modactions.warn(rt, bot, message.chat.id, uid, admin_id=_admin_id(message), reason=reason or None)
    extra = {"warned": "", "muted": " → muted 1h", "banned": " → banned"}[outcome]
    await message.reply(f"⚠️ {esc(label)} warned ({count}/{rt.thr['warn_ban_at']}){extra}.")


@router.message(Command("warnings"))
async def cmd_warnings(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    uid, label, _ = await resolve_target(message, command, bot, rt)
    if uid is None:
        return
    count = await rt.db.get_warnings(uid)
    logs = await rt.db.recent_logs(uid, 5)
    hist = "\n".join(f"• {esc(r['action'])}" + (f" — {esc(r['reason'])}" if r["reason"] else "") for r in logs)
    await message.reply(f"{esc(label)}: {count} warning(s).\n{hist}" if hist else f"{esc(label)}: {count} warning(s).")


@router.message(Command("clearwarnings"))
async def cmd_clearwarnings(message: Message, command: CommandObject, bot: Bot, rt: Runtime) -> None:
    if not await require_admin(message, bot, rt):
        return
    uid, label, _ = await resolve_target(message, command, bot, rt)
    if uid is None:
        return
    await rt.db.clear_warnings(uid)
    await modactions.record(rt, bot, admin_id=_admin_id(message), target_id=uid, action="clearwarnings")
    await message.reply(f"🧹 Cleared warnings for {esc(label)}.")


@router.message(Command("purge"))
async def cmd_purge(message: Message, bot: Bot, rt: Runtime) -> None:
    """Delete everything from the replied-to message up to this command (max 100)."""
    if not await require_admin(message, bot, rt):
        return
    if not message.reply_to_message:
        await message.reply("Reply to the first message you want deleted. Max 100 messages.")
        return
    start, end = message.reply_to_message.message_id, message.message_id
    ids = list(range(start, end + 1))[-100:]
    await safe(lambda: bot.delete_messages(message.chat.id, ids), what="purge")
    await modactions.record(rt, bot, admin_id=_admin_id(message), target_id=0, action=f"purge {len(ids)}")
