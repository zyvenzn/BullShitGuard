"""Pure validation helpers (no Telegram imports, safe to unit-test)."""
from __future__ import annotations

from urllib.parse import urlparse

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def is_solana_address(value: str) -> bool:
    """True if `value` is valid base58 that decodes to exactly 32 bytes.

    This only checks the *shape* of a Solana public key. It cannot tell you
    whether the address is a real token mint. Never treat it as proof.
    """
    s = (value or "").strip()
    if not 32 <= len(s) <= 44:
        return False
    n = 0
    for ch in s:
        i = _B58.find(ch)
        if i < 0:
            return False
        n = n * 58 + i
    pad = len(s) - len(s.lstrip("1"))
    raw_len = (n.bit_length() + 7) // 8
    return pad + raw_len == 32


def is_https_url(value: str) -> bool:
    s = (value or "").strip()
    if not s or len(s) > 300 or any(c.isspace() for c in s):
        return False
    try:
        p = urlparse(s)
    except ValueError:
        return False
    host = p.hostname or ""
    return p.scheme == "https" and "." in host and not p.username and not p.password
