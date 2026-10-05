"""Scam / phishing scoring. Pure functions, no Telegram imports.

Design: a message earns points from several weak signals. Single normal crypto
words ("airdrop", "wallet") score low on their own, so regular chat is not
punished. Only combinations (bait + link, seed-phrase request, lookalike
domains) cross the delete threshold.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import urlparse

_TLDS = (
    "com|io|fi|xyz|top|click|site|online|live|app|net|org|co|me|gg|ly|fun|cc|ru|link|info|"
    "vip|club|pro|tk|ml|ga|cf|gq|to|so|ag|sh|ai|ws|cyou|icu|buzz|rest|work"
)
URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+"
    r"|\b(?:[a-z0-9-]+\.)+(?:" + _TLDS + r")(?![a-z0-9-])(?:/[^\s<>\"']*)?",
    re.I,
)

SHORTENERS = {"bit.ly", "tinyurl.com", "cutt.ly", "is.gd", "rb.gy", "t.ly", "shorturl.at", "tiny.cc", "goo.gl", "ow.ly"}
SUSPICIOUS_TLDS = {"xyz", "top", "click", "tk", "ml", "ga", "cf", "gq", "vip", "site", "online", "cyou", "icu", "buzz", "rest", "work"}

# brand token -> official hosts. A host containing the token but not belonging
# to the official hosts is treated as a lookalike.
BRANDS: dict[str, tuple[str, ...]] = {
    "phantom": ("phantom.app", "phantom.com"),
    "solflare": ("solflare.com",),
    "pumpfun": ("pump.fun",),
    "pump-fun": ("pump.fun",),
    "raydium": ("raydium.io",),
    "dexscreener": ("dexscreener.com",),
    "jupiter": ("jup.ag",),
    "metamask": ("metamask.io",),
    "binance": ("binance.com",),
    "coinbase": ("coinbase.com",),
    "telegram": ("telegram.org", "t.me", "telegram.me"),
}
OFFICIAL_HOSTS = sorted({h for hosts in BRANDS.values() for h in hosts})

_SEED_TERM = (
    r"(?:seed\s*phrase|recovery\s*phrase|secret\s*phrase|secret\s*recovery|mnemonic|"
    r"private\s*key|12\s*words|24\s*words|12[- ]word|24[- ]word)"
)
_ASK_VERB = r"(?:send|share|give|dm|pm|enter|type|paste|provide|verify|submit|drop|tell|show|post|need|require|input|import|ask)"
SEED_ASK_RE = re.compile(rf"{_ASK_VERB}\b.{{0,60}}{_SEED_TERM}|{_SEED_TERM}.{{0,60}}\b{_ASK_VERB}", re.I | re.S)
NEGATED_RE = re.compile(
    rf"\b(?:never|don'?t|do\s+not|dont|jangan|stop|won'?t|will\s+not)\s+(?:\w+\s+){{0,2}}{_ASK_VERB}\b", re.I
)
WALLET_BAIT_RE = re.compile(r"\b(?:connect|validate|verify|sync|link|restore|rectify|import)\s+(?:your\s+|ur\s+)?wallet\b", re.I)
CLAIM_RE = re.compile(r"\bclaim\s+(?:your\s+|ur\s+)?(?:airdrop|reward|rewards|tokens?|bonus|free|prize)\b", re.I)
SEND_SOL_RE = re.compile(r"\bsend\s+(?:\d+(?:\.\d+)?\s*)?sol\b.{0,40}\b(?:claim|receive|get|double|back|airdrop|win|bonus)\b", re.I | re.S)
AIRDROP_RE = re.compile(r"\b(?:airdrop|presale|pre-sale|private\s+sale|whitelist\s+spot)\b", re.I)
ADMIN_CLAIM_RE = re.compile(
    r"\b(?:i\s*am|i'?m|this\s+is)\s+(?:an?\s+|the\s+)?(?:admin|mod|moderator|support|official\s+support)\b"
    r"|\bofficial\s+support\b|\bsupport\s+team\b|\badmin\s+here\b",
    re.I,
)
DM_BAIT_RE = re.compile(r"\b(?:dm\s+me|message\s+me\s+(?:privately|in\s+dm)|inbox\s+me|pm\s+me|text\s+me\s+(?:for|to))\b", re.I)


@dataclass
class ScanResult:
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    unknown_links: list[str] = field(default_factory=list)

    def add(self, points: int, reason: str) -> None:
        self.score += points
        self.reasons.append(reason)


def normalize_link(raw: str) -> tuple[str, str]:
    """Return (host, path) lowercased, without scheme/www/port/userinfo."""
    raw = raw.strip().rstrip(".,;:!?)]}'\"")
    try:
        p = urlparse(raw if "://" in raw else "http://" + raw)
        host = (p.hostname or "").lower().removeprefix("www.")
        path = (p.path or "").lower()
    except ValueError:
        return "", ""
    return host, path


def extract_links(text: str) -> list[str]:
    return [m.group(0).rstrip(".,;:!?)]}'\"") for m in URL_RE.finditer(text or "")]


def _host_matches(host: str, entry: str) -> bool:
    return host == entry or host.endswith("." + entry)


def is_allowed(host: str, path: str, allowlist: tuple[str, ...] | list[str]) -> bool:
    for entry in allowlist:
        entry = entry.lower().strip().removeprefix("www.")
        if "/" in entry:
            eh, _, ep = entry.partition("/")
            if _host_matches(host, eh) and path.startswith("/" + ep.strip("/")):
                return True
        elif _host_matches(host, entry):
            return True
    return False


def scan_message(text: str, allowlist: tuple[str, ...] | list[str] = (), *, extra_urls: list[str] | None = None,
                 impersonating_admin: bool = False) -> ScanResult:
    """Score `text` (plus any hidden entity URLs). Higher = more suspicious."""
    text = text or ""
    res = ScanResult()
    t = unicodedata.normalize("NFKC", text)

    # 1. seed phrase / private key requests (instant delete)
    if SEED_ASK_RE.search(t) and not NEGATED_RE.search(t):
        res.add(5, "seed_or_key_request")

    # 2. links
    raw_links = extract_links(t) + [u for u in (extra_urls or []) if u]
    unknown = 0
    for raw in dict.fromkeys(raw_links):
        host, path = normalize_link(raw)
        if not host:
            continue
        res.links.append(raw)
        allowed = is_allowed(host, path, allowlist)
        if allowed:
            continue
        res.unknown_links.append(raw)
        if unknown < 3:
            res.add(1, f"unknown_link:{host}")
            unknown += 1
        if host in SHORTENERS:
            res.add(2, f"shortener:{host}")
        tld = host.rsplit(".", 1)[-1]
        if tld in SUSPICIOUS_TLDS:
            res.add(1, f"suspicious_tld:{tld}")
        if "xn--" in host:
            res.add(2, f"punycode:{host}")
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
            res.add(2, "ip_host")
        for brand, officials in BRANDS.items():
            if brand in host and not any(_host_matches(host, o) for o in officials):
                res.add(3, f"lookalike:{brand}")
                break
        else:
            for off in OFFICIAL_HOSTS:
                if off in host and not _host_matches(host, off):
                    res.add(3, f"spoof:{off}")
                    break
        if "bullshit" in host and not allowed:
            res.add(3, "lookalike:bullshit")

    has_unknown_link = bool(res.unknown_links)

    # 3. bait phrases
    bait = False
    if WALLET_BAIT_RE.search(t):
        res.add(3, "wallet_connect_bait")
        bait = True
    if CLAIM_RE.search(t):
        res.add(3, "claim_bait")
        bait = True
    if SEND_SOL_RE.search(t):
        res.add(4, "send_sol_to_claim")
        bait = True
    if AIRDROP_RE.search(t):
        res.add(1, "airdrop_presale_word")
        if has_unknown_link:
            res.add(2, "airdrop_presale_with_link")
        bait = True
    if ADMIN_CLAIM_RE.search(t):
        res.add(3, "fake_admin_claim")
        bait = True
    if DM_BAIT_RE.search(t):
        res.add(2, "dm_bait")
        bait = True

    if bait and has_unknown_link:
        res.add(2, "bait_plus_link")
    if impersonating_admin:
        res.add(3, "admin_lookalike_name")
    return res


def verdict(score: int, *, delete_at: int, warn_at: int, ban_at: int) -> str:
    if score >= ban_at:
        return "ban"
    if score >= delete_at:
        return "delete"
    if score >= warn_at:
        return "warn"
    return "ok"


# ---------------------------------------------------------------- impersonation
_HOMOGLYPHS = str.maketrans(
    {"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s",
     "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ѕ": "s"}
)


def _norm_name(name: str) -> str:
    n = unicodedata.normalize("NFKC", name or "").lower().translate(_HOMOGLYPHS)
    return re.sub(r"[^a-z0-9]", "", n)


def looks_like_admin(user_names: list[str], admin_names: list[str]) -> bool:
    """True if any of the user's names equals / closely resembles an admin name.

    Short names are ignored to avoid false positives on common first names.
    """
    users = {_norm_name(n) for n in user_names if n}
    admins = {_norm_name(n) for n in admin_names if n}
    for u in users:
        if len(u) < 4:
            continue
        for a in admins:
            if len(a) < 4:
                continue
            if u == a:
                return True
            if len(u) >= 6 and len(a) >= 6 and SequenceMatcher(None, u, a).ratio() >= 0.88:
                return True
    return False
