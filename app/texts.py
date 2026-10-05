"""All user-facing copy. Telegram HTML. No profit promises, no invented data."""
from __future__ import annotations

import random
import re

from .utils import esc

CA_COMING_SOON = "COMING SOON"

WELCOME_DEFAULT = (
    "🚨 <b>BULLSHIT DETECTED</b> 🚨\n\n"
    "Welcome, {first_name}.\n\n"
    "You just walked into the dumbest corner of CT.\n\n"
    "📉 No financial advice.\n"
    "📈 No guaranteed gains.\n"
    "🧠 No one here knows what they're doing.\n\n"
    "There is only:\n\n"
    "<b>BULL.\nSHIT.\nMEMES.</b>\n\n"
    "Read the rules, stay respectful, and enjoy the chaos.\n\n"
    "Welcome to the herd. 🐂"
)

VERIFY_PROMPT = "\n\n👇 Tap the button to prove you're not a bot. You have {minutes} min or you get kicked."
VERIFY_BUTTON = "🐂 I'M STUPID ENOUGH (VERIFY)"

RULES_DEFAULT = (
    "🐂 <b>BULLSHIT — THE RULES</b>\n\n"
    "1. Don't be an asshole.\n"
    "2. No scams.\n"
    "3. No phishing.\n"
    "4. No spam.\n"
    "5. No unsolicited shilling.\n"
    "6. Memes are welcome.\n"
    "7. Do your own research.\n"
    "8. Never ask for seed phrases/private keys.\n"
    "9. Verify official links.\n"
    "10. Listen to moderators.\n\n"
    "<b>STAY STUPID.\nSTAY BULLISH.</b> 🐂"
)

SCAM_ALERT = (
    "🚨 <b>SCAM ALERT</b>\n\n"
    "Never share your seed phrase or private key.\n\n"
    "BULLSHIT admins will NEVER ask for them. Admins also never DM first.\n\n"
    "🐂 Stay safe."
)

HELP_TEXT = (
    "🐂 <b>BULLSHIT BOT</b>\n\n"
    "/about — what is this\n"
    "/rules — the rules\n"
    "/ca — contract address\n"
    "/links — official links\n"
    "/stats — community stats\n"
    "/gm /gn /thesis /wen /bullshit — nonsense\n\n"
    "NO UTILITY. JUST BULLSHIT."
)

ADMIN_HELP = (
    "🛠 <b>ADMIN</b>\n\n"
    "<b>Moderation</b> (reply or @username/id)\n"
    "/ban · /unban · /kick\n"
    "/mute [10m|2h|1d] [reason] · /unmute\n"
    "/warn [reason] · /warnings · /clearwarnings\n"
    "/purge (reply to the first message to delete)\n"
    "/lock · /unlock — freeze / unfreeze chat\n"
    "/lockdown — raid mode (no links/forwards/media from non-admins)\n\n"
    "<b>Config</b>\n"
    "/settings · /setwelcome · /setrules\n"
    "/setthreshold &lt;name&gt; &lt;value&gt;\n"
    "/announce &lt;text&gt; (+ optional [Label|https://url] button lines)\n\n"
    "<b>Owner only</b>\n"
    "/setca &lt;address|clear&gt; · /setlinks &lt;x|website|buy|telegram&gt; &lt;url|clear&gt;"
)

GM_REPLIES = ["GM.\n\nAnother day.\nAnother candle.\nAnother piece of bullshit. 🐂"]
GN_REPLIES = ["GN.\n\nMay your bags survive the night. 🐂"]
THESIS_REPLIES = ["bull.\n\nshit.\n\nthat's the thesis."]
WEN_REPLIES = [
    "I asked BULLSHIT.\n\nBULLSHIT said:\n\nprobably bullshit. 🐂",
    "wen? the bull doesn't own a calendar. 🐂",
    "wen what? the bull is still reading the chart upside down.",
]
BULLSHIT_REPLIES = [
    "BULLSHIT.\n\nYes, that's the whole product. 🐂",
    "No utility. No promises. Just a stupid bull. 🐂",
    "The bull has no roadmap. The bull has vibes.",
]

# (key, pattern, replies). Matched against normal group messages.
TRIGGERS: list[tuple[str, re.Pattern[str], list[str]]] = [
    ("wen", re.compile(r"\bwen\s+(?:moon|lambo|pump|mars)\b", re.I), WEN_REPLIES),
    ("thesis", re.compile(r"\b(?:what'?s|whats|what\s+is)\s+the\s+(?:thesis|plan)\b|\bthesis\s*\?", re.I), THESIS_REPLIES),
    ("fa", re.compile(r"\bis\s+this\s+(?:financial\s+)?advice\b|\bfinancial\s+advice\s*\?", re.I),
     ["Absolutely not.\n\nI'm literally BULLSHIT."]),
    ("why", re.compile(r"\bwhy\s+(?:should\s+i\s+)?buy\b", re.I),
     ["That's between you and your financial decisions."]),
]
CA_QUESTION_RE = re.compile(r"^\s*(?:ca|contract|contract\s+address|ca\s+pls|ca\s+please)\s*\??\s*$", re.I)


def pick_reply(text: str, rng: random.Random | None = None) -> tuple[str, str] | None:
    """Return (trigger_key, reply) for the first matching trigger, else None."""
    rng = rng or random
    for key, pattern, replies in TRIGGERS:
        if pattern.search(text or ""):
            return key, rng.choice(replies)
    return None


_VARS = re.compile(r"\{(first_name|username|mention|group_name)\}")


def render_welcome(template: str, *, first_name: str, username: str | None, user_id: int, group_name: str) -> str:
    """Single-pass variable replacement; values are HTML-escaped (no format injection)."""
    name = esc(first_name or "anon")
    values = {
        "{first_name}": name,
        "{username}": "@" + esc(username) if username else name,
        "{mention}": f'<a href="tg://user?id={int(user_id)}">{name}</a>',
        "{group_name}": esc(group_name or "BULLSHIT"),
    }
    return _VARS.sub(lambda m: values[m.group(0)], template)


def build_about(*, x: str, website: str, ca: str) -> str:
    lines = [
        "🐂 <b>BULLSHIT</b>",
        "",
        "A stupid bull living in a market full of smart people.",
        "",
        "No utility.",
        "No promises.",
        "Just memes.",
        "",
        "<b>Ticker:</b>\n$BULLSHIT",
        "",
        "<b>Network:</b>\nSolana",
        "",
        f"<b>Official X:</b>\n{esc(x) if x else 'coming soon'}",
        "",
        f"<b>Website:</b>\n{esc(website) if website else 'coming soon'}",
        "",
        f"<b>Contract:</b>\n{'<code>' + esc(ca) + '</code>' if ca else 'CA: ' + CA_COMING_SOON}",
        "",
        "<i>Not financial advice. Meme token. You can lose everything.</i>",
    ]
    return "\n".join(lines)


def build_ca(ca: str) -> str:
    if not ca:
        return f"🐂 <b>CONTRACT STATUS</b>\n\nCA:\n<b>{CA_COMING_SOON}</b>\n\nDon't trust anyone DMing you a \"CA\". Official CA is posted here and on the official X only."
    return f"🐂 <b>BULLSHIT CONTRACT</b>\n\nSolana:\n<code>{esc(ca)}</code>\n\nAlways verify against the official X before buying."


def build_stats(*, members: int | None, messages: int, warnings: int, new_members: int) -> str:
    lines = ["🐂 <b>BULLSHIT COMMUNITY</b>", ""]
    if members is not None:
        lines += ["Members:", str(members), ""]
    lines += [
        "Messages today:", str(messages), "",
        "Warnings today:", str(warnings), "",
        "New members today:", str(new_members), "",
        "<i>Daily numbers are counted by this bot (UTC).</i>",
    ]
    return "\n".join(lines)
