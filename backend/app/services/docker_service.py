import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar

import docker
import docker.errors

_client_lock = threading.Lock()
_client: docker.DockerClient | None = None

T = TypeVar("T")


def _offload(fn: Callable[[], T]) -> T:
    """
    Run blocking Docker SDK calls off the eventlet hub.

    Gunicorn uses ``--worker-class eventlet``; blocking ``docker.containers`` in a
    request handler freezes every HTTP/WebSocket until the call returns (looks like
    Start/Remove "do nothing" in the UI).
    """
    try:
        from eventlet import tpool

        return tpool.execute(fn)
    except (ImportError, AttributeError, RuntimeError):
        return fn()


def _get_client() -> docker.DockerClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = docker.from_env()
        return _client


def default_container_name(profile_id: int) -> str:
    return f"gsm-server-{profile_id}"


def resolve_volume_host_path(profile) -> str:
    """Absolute path on the host (mounted into backend container)."""
    raw = (profile.volume_path or "").strip()
    if raw.startswith("/"):
        return raw
    root = os.environ.get("SERVER_DATA_ROOT", "/data/servers").rstrip("/")
    return f"{root}/{profile.id}"


def _normalize_env_vars(raw: dict | None) -> dict[str, str]:
    """Docker expects string values; JSON may contain booleans."""
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        if v is None:
            continue
        key = str(k)
        if isinstance(v, bool):
            out[key] = "TRUE" if v else "FALSE"
        else:
            out[key] = str(v)
    return out


def _game_container_dns() -> list[str] | None:
    """Optional DNS servers for game containers (fixes some Docker Desktop / VPN DNS issues)."""
    raw = os.environ.get("GAME_CONTAINER_DNS", "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    return parts or None


def _container_environment(profile) -> dict[str, str]:
    """
    Merge safe defaults for common Minecraft images (e.g. itzg/minecraft-server).
    User-provided keys always win. Missing EULA/TYPE often causes exit code 2 + restart loops.
    """
    env = _normalize_env_vars(profile.env_vars)
    gt = (profile.game_type or "").lower()
    img = (profile.docker_image or "").lower()
    if "minecraft" in gt or "itzg" in img or "minecraft" in img:
        defaults = {
            "EULA": "TRUE",
            "TYPE": "VANILLA",
            "MEMORY": "2G",
            "TUNE_VIRTUALIZED": "TRUE",
            "ONLINE_MODE": "FALSE",
        }
        for key, val in defaults.items():
            env.setdefault(key, val)
    return env


def _try_start_sync(name: str, host_data: str) -> tuple[str, str | None]:
    """Returns (kind, container_id). kind is running|started|missing."""
    os.makedirs(host_data, exist_ok=True)
    client = _get_client()
    try:
        old = client.containers.get(name)
        old.reload()
        if old.status == "running":
            return "running", old.id
        old.start()
        return "started", old.id
    except docker.errors.NotFound:
        return "missing", None


def try_start_synchronously(profile) -> dict[str, Any] | None:
    """
    If the container already exists: return status (running / started).
    If it does not exist yet, return None — caller must run create_game_container
    (often slow: image pull) off the request thread.
    """
    name = profile.container_name or default_container_name(profile.id)
    host_data = resolve_volume_host_path(profile)

    kind, cid = _offload(lambda: _try_start_sync(name, host_data))
    if kind == "missing":
        return None
    profile.container_name = name
    if kind == "running":
        return {"status": "running", "container_id": cid, "name": name}
    return {"status": "started", "container_id": cid, "name": name}


def create_game_container(profile) -> dict[str, Any]:
    """Create and start a new container (may block a long time while Docker pulls the image)."""
    client = _get_client()
    name = profile.container_name or default_container_name(profile.id)
    host_data = resolve_volume_host_path(profile)
    os.makedirs(host_data, exist_ok=True)
    ports = {f"{profile.port}/tcp": profile.port}
    env = _container_environment(profile)
    run_kw: dict[str, Any] = {
        "detach": True,
        "ports": ports,
        "environment": env,
        "volumes": {host_data: {"bind": "/data", "mode": "rw"}},
        "restart_policy": {"Name": "unless-stopped"},
    }
    dns = _game_container_dns()
    if dns:
        run_kw["dns"] = dns
    container = client.containers.run(profile.docker_image, name=name, **run_kw)
    profile.container_name = name
    return {"status": "created", "container_id": container.id, "name": name}


def start_server(profile) -> dict[str, Any]:
    r = try_start_synchronously(profile)
    if r is not None:
        return r
    return create_game_container(profile)


def _stop_server_sync(name: str, timeout: int) -> dict[str, Any]:
    client = _get_client()
    try:
        c = client.containers.get(name)
        c.stop(timeout=timeout)
        return {"status": "stopped", "name": name}
    except docker.errors.NotFound:
        return {"status": "not_found", "name": name}


def stop_server(profile, timeout: int = 30) -> dict[str, Any]:
    name = profile.container_name or default_container_name(profile.id)
    return _offload(lambda: _stop_server_sync(name, timeout))


def _force_remove_container_obj(c) -> None:
    try:
        c.kill()
    except docker.errors.APIError:
        pass
    except Exception:
        pass
    c.remove(v=False, force=True)


def _remove_container_sync(profile_id: int, container_name_db: str | None) -> dict[str, Any]:
    """
    Remove by canonical name, optional DB name, then scan all containers (handles name drift,
    leading slashes, and Docker Desktop quirks).
    """
    client = _get_client()
    def_name = default_container_name(profile_id)
    candidates: list[str] = [def_name]
    if container_name_db:
        cn = container_name_db.strip().lstrip("/")
        if cn and cn not in candidates:
            candidates.append(cn)

    removed: list[str] = []
    last_err: str | None = None

    for name in candidates:
        try:
            c = client.containers.get(name)
            _force_remove_container_obj(c)
            removed.append(name)
        except docker.errors.NotFound:
            continue
        except Exception as e:
            last_err = f"{name}: {e}"

    if not removed:
        try:
            want = {def_name}
            if container_name_db:
                want.add(container_name_db.strip().lstrip("/"))
            for c in client.containers.list(all=True):
                n = (c.name or "").lstrip("/")
                if n in want or n == def_name:
                    try:
                        _force_remove_container_obj(c)
                        removed.append(n)
                    except Exception as e:
                        last_err = f"{n}: {e}"
        except Exception as e:
            last_err = str(e)

    if removed:
        return {"status": "removed", "name": removed[0], "names": removed}
    if last_err:
        return {
            "status": "error",
            "message": last_err,
            "searched": candidates,
        }
    return {"status": "not_found", "searched": candidates}


def remove_container(profile) -> dict[str, Any]:
    """Delete the Docker container (profile row is kept). Use after a crash loop before Start."""
    return _offload(
        lambda: _remove_container_sync(profile.id, profile.container_name)
    )


def _get_container_sync(name: str):
    client = _get_client()
    try:
        return client.containers.get(name)
    except docker.errors.NotFound:
        return None


def get_container(profile):
    name = profile.container_name or default_container_name(profile.id)
    return _offload(lambda: _get_container_sync(name))


def _container_status_sync(name: str) -> dict[str, Any]:
    c = _get_container_sync(name)
    if not c:
        return {"running": False, "status": "not_found"}
    c.reload()
    return {"running": c.status == "running", "status": c.status, "id": c.short_id}


def container_status(profile) -> dict[str, Any]:
    name = profile.container_name or default_container_name(profile.id)
    return _offload(lambda: _container_status_sync(name))


def stream_logs(container, tail: int = 200):
    if not container:
        return
    try:
        for line in container.logs(stream=True, follow=True, tail=tail):
            yield line.decode(errors="replace")
    except Exception:
        return


def _one_shot_stats_sync(name: str) -> dict[str, Any] | None:
    c = _get_container_sync(name)
    if not c:
        return None
    try:
        c.reload()
        if c.status != "running":
            return {"cpu_percent": 0.0, "mem_usage_mb": 0.0, "mem_limit_mb": 0.0}
        s = c.stats(stream=False)
        return _parse_stats_snapshot(s)
    except Exception:
        return None


def stats_snapshot_for_profile(profile) -> dict[str, Any] | None:
    """CPU/RAM snapshot; single tpool round-trip."""
    name = profile.container_name or default_container_name(profile.id)
    return _offload(lambda: _one_shot_stats_sync(name))


def one_shot_stats(container) -> dict[str, Any] | None:
    """Legacy: stats for an already-resolved container (blocking — avoid from eventlet)."""
    if not container:
        return None
    try:
        container.reload()
        if container.status != "running":
            return {"cpu_percent": 0.0, "mem_usage_mb": 0.0, "mem_limit_mb": 0.0}
        s = container.stats(stream=False)
        return _parse_stats_snapshot(s)
    except Exception:
        return None


def _parse_stats_snapshot(s: dict) -> dict[str, Any]:
    cpu_delta = s.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0) - s.get(
        "precpu_stats", {}
    ).get("cpu_usage", {}).get("total_usage", 0)
    system_delta = s.get("cpu_stats", {}).get("system_cpu_usage", 0) - s.get(
        "precpu_stats", {}
    ).get("system_cpu_usage", 0)
    cpu_percent = 0.0
    if system_delta > 0 and cpu_delta > 0:
        cpus = len(s.get("cpu_stats", {}).get("cpu_usage", {}).get("percpu_usage", []) or []) or 1
        cpu_percent = (cpu_delta / system_delta) * cpus * 100.0
        cpu_percent = min(round(cpu_percent, 2), 10000.0)

    mem = s.get("memory_stats", {}) or {}
    usage = mem.get("usage", 0) or 0
    limit = mem.get("limit", 0) or 0
    return {
        "cpu_percent": round(cpu_percent, 2),
        "mem_usage_mb": round(usage / (1024 * 1024), 2),
        "mem_limit_mb": round(limit / (1024 * 1024), 2) if limit else 0.0,
    }
