"""Helpers for comparing user ids (JWT / ORM) without type quirks."""


def same_user_id(left, right) -> bool:
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return False
