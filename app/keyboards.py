from __future__ import annotations

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from .texts import VERIFY_BUTTON


def main_menu(x_url: str = "") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🐂 ABOUT", callback_data="menu:about"),
         InlineKeyboardButton(text="📜 RULES", callback_data="menu:rules")],
        [InlineKeyboardButton(text="🔗 LINKS", callback_data="menu:links"),
         InlineKeyboardButton(text="💰 CONTRACT", callback_data="menu:ca")],
    ]
    if x_url:
        rows.append([InlineKeyboardButton(text="🐦 X", url=x_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def links_menu(links: dict[str, str]) -> InlineKeyboardMarkup | None:
    spec = [("x", "🐦 X"), ("website", "🌐 WEBSITE"), ("buy", "💰 BUY $BULLSHIT"), ("telegram", "💬 TELEGRAM")]
    rows = [[InlineKeyboardButton(text=label, url=links[key])] for key, label in spec if links.get(key)]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def ca_menu(ca: str) -> InlineKeyboardMarkup | None:
    if not ca:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="COPY CA", copy_text=CopyTextButton(text=ca))]]
    )


def verify_menu(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=VERIFY_BUTTON, callback_data=f"verify:{user_id}")]]
    )


def confirm_menu(action: str, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ CONFIRM", callback_data=f"{action}:yes:{token}"),
            InlineKeyboardButton(text="✖ CANCEL", callback_data=f"{action}:no:{token}"),
        ]]
    )


def announce_buttons(buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, url=u)] for t, u in buttons])
