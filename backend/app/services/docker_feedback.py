"""Thread-safe messages from background Docker jobs (shown on GET /servers/...)."""

import threading

_lock = threading.Lock()
_errors: dict[int, str] = {}


def set_docker_error(profile_id: int, message: str) -> None:
    with _lock:
        _errors[profile_id] = (message or "")[:4000]


def clear_docker_error(profile_id: int) -> None:
    with _lock:
        _errors.pop(profile_id, None)


def get_docker_error(profile_id: int) -> str | None:
    with _lock:
        return _errors.get(profile_id)
