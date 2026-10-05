"""Shared runtime state: settings + DB + in-memory trackers. No aiogram imports."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import THRESHOLDS, Settings
from .db import Database
from .permissions import is_configured_admin, is_owner, status_is_admin
from .spam import Cooldown, FloodTracker

ADMIN_CACHE_TTL = 300


def utc_day(now: float | None = None) -> str:
    return datetime.fromtimestamp(now if now is not None else time.time(), tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class Runtime:
    settings: Settings
    db: Database
    tracker: FloodTracker
    cooldowns: Cooldown = field(default_factory=Cooldown)
    bot_id: int = 0
    thr: dict[str, int] = field(default_factory=dict)
    strict: bool = False
    pending_ca: dict[str, tuple[str, int, float]] = field(default_factory=dict)
    _admin_cache: dict[tuple[int, int], tuple[float, bool]] = field(default_factory=dict)
    _admin_names: dict[int, tuple[float, list[str]]] = field(default_factory=dict)

    # ------------------------------------------------------------- loading
    async def load(self) -> None:
        stored = await self.db.all_settings()
        self.thr = {}
        for name in THRESHOLDS:
            raw = stored.get(f"thr:{name}")
            self.thr[name] = int(raw) if raw is not None and raw.lstrip("-").isdigit() else getattr(self.settings, name)
        self.strict = stored.get("strict") == "1"
        self.sync_tracker()

    def sync_tracker(self) -> None:
        self.tracker.configure(
            max_messages=self.thr["flood_messages"],
            window_seconds=self.thr["flood_seconds"],
            repeat_limit=self.thr["repeat_limit"],
        )

    async def set_threshold(self, name: str, value: int) -> str | None:
        """Returns an error string, or None on success."""
        if name not in THRESHOLDS:
            return "Unknown setting."
        lo, hi = THRESHOLDS[name]
        if not lo <= value <= hi:
            return f"{name} must be between {lo} and {hi}."
        trial = {**self.thr, name: value}
        if trial["warn_ban_at"] <= trial["warn_mute_at"]:
            return "warn_ban_at must be greater than warn_mute_at."
        self.thr[name] = value
        await self.db.set_setting(f"thr:{name}", str(value))
        self.sync_tracker()
        return None

    async def set_strict(self, on: bool) -> None:
        self.strict = on
        await self.db.set_setting("strict", "1" if on else "0")

    # ----------------------------------------------------- effective config
    async def get_ca(self) -> str:
        return (await self.db.get_setting("ca")) or self.settings.ca

    async def get_links(self) -> dict[str, str]:
        s = self.settings
        base = {"x": s.official_x, "website": s.official_website, "buy": s.buy_link, "telegram": s.telegram_link}
        stored = await self.db.all_settings()
        for k in base:
            if stored.get(f"link:{k}"):
                base[k] = stored[f"link:{k}"]
        return base

    async def allowlist(self) -> tuple[str, ...]:
        # official links set at runtime are allowed too
        extra: list[str] = []
        from urllib.parse import urlparse
        for k, url in (await self.get_links()).items():
            if not url:
                continue
            p = urlparse(url)
            host = (p.hostname or "").removeprefix("www.")
            extra.append(f"{host}{p.path}".rstrip("/").lower() if k == "telegram" else host)
        return tuple(dict.fromkeys((*self.settings.link_allowlist, *[e for e in extra if e and e != "t.me"])))

    # ---------------------------------------------------------- permissions
    def is_owner(self, user_id: int) -> bool:
        return is_owner(user_id, self.settings.owner_ids)

    async def is_admin(self, bot: Any, chat_id: int, user_id: int, *, now: float | None = None) -> bool:
        if is_configured_admin(user_id, self.settings.owner_ids, self.settings.admin_ids):
            return True
        now = now if now is not None else time.time()
        key = (chat_id, user_id)
        hit = self._admin_cache.get(key)
        if hit and now - hit[0] < ADMIN_CACHE_TTL:
            return hit[1]
        ok = False
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            ok = status_is_admin(member.status)
        except Exception:  # noqa: BLE001 - unknown => not admin (fail closed)
            ok = False
        self._admin_cache[key] = (now, ok)
        return ok

    async def admin_names(self, bot: Any, chat_id: int, *, now: float | None = None) -> list[str]:
        now = now if now is not None else time.time()
        hit = self._admin_names.get(chat_id)
        if hit and now - hit[0] < ADMIN_CACHE_TTL:
            return hit[1]
        names: list[str] = []
        try:
            for m in await bot.get_chat_administrators(chat_id):
                u = m.user
                if u.is_bot:
                    continue
                full = " ".join(p for p in (u.first_name, u.last_name) if p)
                names += [n for n in (u.first_name, full, u.username) if n]
        except Exception:  # noqa: BLE001
            pass
        self._admin_names[chat_id] = (now, names)
        return names

    def forget_admins(self) -> None:
        self._admin_cache.clear()
        self._admin_names.clear()
