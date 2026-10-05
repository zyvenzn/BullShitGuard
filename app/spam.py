"""In-memory flood / repeat / cooldown tracking. Pure, no Telegram imports."""
from __future__ import annotations

import re
from collections import defaultdict, deque


def mute_minutes_for(strike: int, base: int) -> int:
    """Escalating mute: base, 2x, 4x ... capped at 24h."""
    return min(base * (2 ** max(strike - 1, 0)), 24 * 60)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


class FloodTracker:
    def __init__(self, max_messages: int = 6, window_seconds: int = 8, repeat_limit: int = 3,
                 repeat_window: int = 60, strike_decay: int = 3600) -> None:
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self.repeat_limit = repeat_limit
        self.repeat_window = repeat_window
        self.strike_decay = strike_decay
        self._times: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._texts: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(deque)
        self._strikes: dict[tuple[int, int], tuple[int, float]] = {}

    def configure(self, **kw: int) -> None:
        for k, v in kw.items():
            if hasattr(self, k) and isinstance(v, int):
                setattr(self, k, v)

    def check(self, chat_id: int, user_id: int, text: str, now: float) -> str | None:
        """Record a message. Returns 'flood', 'repeat' or None."""
        key = (chat_id, user_id)
        times = self._times[key]
        times.append(now)
        while times and now - times[0] > self.window_seconds:
            times.popleft()
        if len(times) > self.max_messages:
            return "flood"

        norm = _norm(text)
        if len(norm) >= 4:
            texts = self._texts[key]
            texts.append((now, norm))
            while texts and now - texts[0][0] > self.repeat_window:
                texts.popleft()
            if sum(1 for _, t in texts if t == norm) >= self.repeat_limit:
                return "repeat"
        return None

    def strike(self, chat_id: int, user_id: int, now: float) -> int:
        key = (chat_id, user_id)
        count, last = self._strikes.get(key, (0, now))
        if now - last > self.strike_decay:
            count = 0
        count += 1
        self._strikes[key] = (count, now)
        # reset counters so one burst isn't punished repeatedly
        self._times[key].clear()
        self._texts[key].clear()
        return count

    def cleanup(self, now: float) -> None:
        horizon = max(self.window_seconds, self.repeat_window) * 2
        for key in [k for k, d in self._times.items() if not d or now - d[-1] > horizon]:
            self._times.pop(key, None)
            self._texts.pop(key, None)
        for key in [k for k, (_, last) in self._strikes.items() if now - last > self.strike_decay]:
            self._strikes.pop(key, None)


class Cooldown:
    """`hit(key, seconds, now)` is True when the action is allowed (and arms it)."""

    def __init__(self) -> None:
        self._last: dict[object, float] = {}

    def hit(self, key: object, seconds: float, now: float) -> bool:
        last = self._last.get(key)
        if last is not None and now - last < seconds:
            return False
        self._last[key] = now
        return True

    def cleanup(self, now: float, older_than: float = 3600) -> None:
        for k in [k for k, t in self._last.items() if now - t > older_than]:
            self._last.pop(k, None)
