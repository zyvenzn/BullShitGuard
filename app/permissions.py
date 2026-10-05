"""Permission rules (pure)."""
from __future__ import annotations

ADMIN_STATUSES = ("creator", "administrator")


def is_owner(user_id: int, owner_ids: frozenset[int]) -> bool:
    return user_id in owner_ids


def is_configured_admin(user_id: int, owner_ids: frozenset[int], admin_ids: frozenset[int]) -> bool:
    return user_id in owner_ids or user_id in admin_ids


def status_is_admin(status: object) -> bool:
    """Accepts aiogram's ChatMemberStatus (str enum) or a plain string."""
    value = getattr(status, "value", status)
    return str(value) in ADMIN_STATUSES
