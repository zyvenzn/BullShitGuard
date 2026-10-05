"""Small pure helpers."""
from __future__ import annotations

import html
import re

from .validators import is_https_url

_DUR_RE = re.compile(r"^(\d{1,4})([smhdw])$", re.I)
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_BTN_RE = re.compile(r"^\[([^\]|]{1,32})\|(https://[^\]\s]+)\]$")


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def parse_duration(token: str) -> int | None:
    """'10m' -> 600. Returns None if invalid. Minimum 60s, maximum 366 days."""
    m = _DUR_RE.match((token or "").strip())
    if not m:
        return None
    secs = int(m.group(1)) * _UNITS[m.group(2).lower()]
    if secs < 60 or secs > 366 * 86400:
        return None
    return secs


def format_duration(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def split_target_args(args: str | None, has_reply: bool) -> tuple[str | None, str]:
    """Return (target_token, rest). With a reply, everything is `rest`."""
    args = (args or "").strip()
    if has_reply:
        return None, args
    if not args:
        return None, ""
    first, _, rest = args.partition(" ")
    return first, rest.strip()


def parse_target_token(token: str | None) -> tuple[int | None, str | None]:
    """'@name' -> (None, 'name'); '12345' -> (12345, None); junk -> (None, None)."""
    if not token:
        return None, None
    token = token.strip()
    if token.lstrip("-").isdigit():
        return int(token), None
    if re.fullmatch(r"@[A-Za-z0-9_]{4,32}", token):
        return None, token[1:]
    return None, None


def strip_command(text: str | None) -> str:
    """Remove the leading '/command' (and optional @botname) from a message."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return text
    parts = text.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def parse_announcement(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split text into body + buttons. Button lines look like `[Label|https://url]`.

    Non-https buttons are ignored. At most 6 buttons.
    """
    body: list[str] = []
    buttons: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        m = _BTN_RE.match(line.strip())
        if m and is_https_url(m.group(2)):
            if len(buttons) < 6:
                buttons.append((m.group(1).strip(), m.group(2)))
            continue
        body.append(line)
    return "\n".join(body).strip(), buttons


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
