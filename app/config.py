"""Settings loaded from environment variables. Nothing secret is hardcoded."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlparse

from .validators import is_https_url, is_solana_address


class ConfigError(ValueError):
    """Raised for invalid configuration. Messages never include secrets."""


# name -> (min, max). Used by /setthreshold.
THRESHOLDS: dict[str, tuple[int, int]] = {
    "flood_messages": (2, 50),
    "flood_seconds": (2, 120),
    "repeat_limit": (2, 20),
    "mute_minutes": (1, 1440),
    "warn_mute_at": (1, 20),
    "warn_ban_at": (2, 50),
    "max_links": (0, 20),
    "probation_hours": (0, 168),
    "verify_timeout_seconds": (30, 3600),
}

DEFAULT_ALLOWED_HOSTS = (
    "x.com",
    "twitter.com",
    "pump.fun",
    "dexscreener.com",
    "solscan.io",
    "solana.com",
)


def _id_set(raw: str | None, name: str) -> frozenset[int]:
    out: set[int] = set()
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            raise ConfigError(f"{name} must be a comma-separated list of integers")
    return frozenset(out)


def _opt_int(raw: str | None, name: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer")


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer")
    lo, hi = THRESHOLDS.get(key.lower(), (0, 10**9))
    if not lo <= value <= hi:
        raise ConfigError(f"{key} must be between {lo} and {hi}")
    return value


def _url(env: Mapping[str, str], key: str) -> str:
    raw = (env.get(key) or "").strip()
    if raw and not is_https_url(raw):
        raise ConfigError(f"{key} must be a valid https:// URL (or empty)")
    return raw


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)
    owner_ids: frozenset[int]
    admin_ids: frozenset[int]
    group_id: int | None
    log_chat_id: int | None
    database_path: str
    ca: str
    official_x: str
    official_website: str
    buy_link: str
    telegram_link: str
    verify_enabled: bool
    coexist_mode: bool
    link_allowlist: tuple[str, ...]
    flood_messages: int
    flood_seconds: int
    repeat_limit: int
    mute_minutes: int
    warn_mute_at: int
    warn_ban_at: int
    max_links: int
    probation_hours: int
    verify_timeout_seconds: int
    scam_delete_score: int
    scam_warn_score: int
    scam_ban_score: int

    def __repr__(self) -> str:  # never leak the token
        return "Settings(<redacted>)"

    @property
    def privileged_ids(self) -> frozenset[int]:
        return self.owner_ids | self.admin_ids

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, require_token: bool = True) -> "Settings":
        env = os.environ if env is None else env

        token = (env.get("BOT_TOKEN") or "").strip()
        if require_token and not token:
            raise ConfigError("BOT_TOKEN is required")

        admin_ids = _id_set(env.get("ADMIN_IDS"), "ADMIN_IDS")
        owner_ids = _id_set(env.get("OWNER_IDS"), "OWNER_IDS") or admin_ids
        if require_token and not (owner_ids | admin_ids):
            raise ConfigError("Set ADMIN_IDS (and ideally OWNER_IDS)")

        ca = (env.get("BULLSHIT_CA") or "").strip()
        if ca and not is_solana_address(ca):
            # Fail loudly. A typo must never silently become the "official" CA.
            raise ConfigError("BULLSHIT_CA is set but is not a valid Solana address")

        x = _url(env, "OFFICIAL_X")
        site = _url(env, "OFFICIAL_WEBSITE")
        buy = _url(env, "BUY_LINK")
        tg = _url(env, "TELEGRAM_LINK")

        hosts = list(DEFAULT_ALLOWED_HOSTS)
        # Own site host is allowed. t.me is only allowed for the exact official link,
        # never as a whole host (otherwise any scam group link would pass).
        for url in (site, buy):
            if url:
                hosts.append((urlparse(url).hostname or "").removeprefix("www."))
        if tg:
            p = urlparse(tg)
            hosts.append(f"{(p.hostname or '').removeprefix('www.')}{p.path}".rstrip("/").lower())
        extra = [h.strip().lower() for h in (env.get("LINK_ALLOWLIST") or "").split(",") if h.strip()]
        allow = tuple(dict.fromkeys(h for h in hosts + extra if h))

        s = cls(
            bot_token=token,
            owner_ids=owner_ids,
            admin_ids=admin_ids,
            group_id=_opt_int(env.get("GROUP_ID"), "GROUP_ID"),
            log_chat_id=_opt_int(env.get("LOG_CHAT_ID"), "LOG_CHAT_ID"),
            database_path=(env.get("DATABASE_PATH") or "data/bullshit.sqlite3").strip(),
            ca=ca,
            official_x=x,
            official_website=site,
            buy_link=buy,
            telegram_link=tg,
            verify_enabled=(env.get("VERIFY_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")),
            coexist_mode=(env.get("COEXIST_MODE", "false").strip().lower() in ("1", "true", "yes", "on")),
            link_allowlist=allow,
            flood_messages=_int(env, "FLOOD_MESSAGES", 6),
            flood_seconds=_int(env, "FLOOD_SECONDS", 8),
            repeat_limit=_int(env, "REPEAT_LIMIT", 3),
            mute_minutes=_int(env, "MUTE_MINUTES", 10),
            warn_mute_at=_int(env, "WARN_MUTE_AT", 3),
            warn_ban_at=_int(env, "WARN_BAN_AT", 5),
            max_links=_int(env, "MAX_LINKS", 2),
            probation_hours=_int(env, "PROBATION_HOURS", 24),
            verify_timeout_seconds=_int(env, "VERIFY_TIMEOUT_SECONDS", 180),
            scam_delete_score=_int(env, "SCAM_DELETE_SCORE", 5),
            scam_warn_score=_int(env, "SCAM_WARN_SCORE", 3),
            scam_ban_score=_int(env, "SCAM_BAN_SCORE", 8),
        )
        if s.warn_ban_at <= s.warn_mute_at:
            raise ConfigError("WARN_BAN_AT must be greater than WARN_MUTE_AT")
        return s
