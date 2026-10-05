"""Telegram call helpers: retry on flood-wait/network, swallow expected API errors."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

log = logging.getLogger("bullshit.tg")


async def safe(call: Callable[[], Awaitable[Any]], *, what: str = "telegram call", retries: int = 3) -> Any:
    """Run `call()`; return None on expected failures instead of raising.

    - flood wait: sleep and retry
    - network hiccup: back off and retry
    - missing rights / deleted user / message gone: log and return None
    """
    for attempt in range(retries + 1):
        try:
            return await call()
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
        except TelegramNetworkError:
            await asyncio.sleep(1.5 * (attempt + 1))
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            log.warning("telegram refused", extra={"what": what, "error": str(e)[:200]})
            return None
        except TelegramAPIError as e:
            log.error("telegram api error", extra={"what": what, "error": str(e)[:200]})
            return None
    log.error("telegram call gave up", extra={"what": what})
    return None


_tasks: set[asyncio.Task] = set()


def delete_later(bot: Any, chat_id: int, message_id: int, delay: float) -> None:
    async def _go() -> None:
        await asyncio.sleep(delay)
        await safe(lambda: bot.delete_message(chat_id, message_id), what="delete_later")

    task = asyncio.create_task(_go())
    _tasks.add(task)  # keep a reference so it isn't garbage-collected mid-sleep
    task.add_done_callback(_tasks.discard)
