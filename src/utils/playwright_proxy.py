"""Chọn proxy cho Playwright: pool file (Webshare) hoặc HTTP(S)_PROXY trong .env."""

from __future__ import annotations

import random
import threading
from pathlib import Path
from urllib.parse import urlparse

from src.core.settings import settings

_lock = threading.Lock()
_cache: tuple[str, float, list[dict[str, str | None]]] | None = None


def _parse_webshare_line(line: str) -> dict[str, str | None] | None:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    parts = s.split(":", 3)
    if len(parts) != 4:
        return None
    host, port, user, password = parts[0], parts[1], parts[2], parts[3]
    if not host or not port:
        return None
    return {
        "server": f"http://{host}:{port}",
        "username": user or None,
        "password": password or None,
    }


def _load_proxy_pool() -> list[dict[str, str | None]]:
    global _cache
    raw = (settings.proxy_list_file or "").strip()
    if not raw:
        return []
    path = Path(raw)
    if not path.is_file():
        return []
    resolved = str(path.resolve())
    mtime = path.stat().st_mtime
    with _lock:
        if _cache and _cache[0] == resolved and _cache[1] == mtime:
            return _cache[2]
        rows: list[dict[str, str | None]] = []
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            p = _parse_webshare_line(line)
            if p:
                rows.append(p)
        _cache = (resolved, mtime, rows)
        return rows


def _proxy_from_env_url() -> dict[str, str | None] | None:
    raw = (settings.https_proxy or settings.http_proxy or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    u = urlparse(raw)
    if not u.hostname:
        return None
    scheme = u.scheme or "http"
    port = u.port
    if port is None:
        port = 443 if scheme == "https" else 80
    server = f"{scheme}://{u.hostname}:{port}"
    return {
        "server": server,
        "username": u.username or None,
        "password": u.password or None,
    }


def _normalize_playwright_proxy(p: dict[str, str | None]) -> dict[str, str]:
    """Playwright: chỉ gửi username/password khi có giá trị."""
    out: dict[str, str] = {"server": str(p["server"])}
    u, pw = p.get("username"), p.get("password")
    if u:
        out["username"] = str(u)
    if pw:
        out["password"] = str(pw)
    return out


def get_playwright_proxy() -> dict[str, str] | None:
    """
    Ưu tiên: PROXY_LIST_FILE (mỗi dòng host:port:user:pass, ví dụ Webshare).
    Fallback: HTTPS_PROXY / HTTP_PROXY (hỗ trợ user:pass trong URL).
    Mỗi lần gọi: random một dòng trong pool (phân tán IP).
    """
    pool = _load_proxy_pool()
    if pool:
        return _normalize_playwright_proxy(random.choice(pool))
    envp = _proxy_from_env_url()
    return _normalize_playwright_proxy(envp) if envp else None


def get_random_proxy_url() -> str | None:
    """
    Trả về proxy URL dạng scheme://user:pass@host:port (nếu có).
    Dùng cho HTTP client như curl_cffi.
    """
    chosen: dict[str, str | None] | None = None
    pool = _load_proxy_pool()
    if pool:
        chosen = random.choice(pool)
    else:
        chosen = _proxy_from_env_url()
    if not chosen:
        return None

    server = str(chosen.get("server") or "").strip()
    if not server:
        return None
    username = chosen.get("username")
    password = chosen.get("password")
    if not username:
        return server

    p = urlparse(server)
    if not p.scheme or not p.hostname:
        return server

    auth = username
    if password:
        auth = f"{auth}:{password}"
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme}://{auth}@{p.hostname}{port}"
