"""Небольшая обёртка над urllib: HTTP-запросы с JSON без внешних библиотек."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class Transport(Protocol):
    """Интерфейс транспорта. В тестах подменяется фейком без сети."""

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict | None = None,
        timeout: float = 30,
    ) -> Any: ...


def urllib_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict | None = None,
    timeout: float = 30,
) -> Any:
    data = None
    headers = dict(headers)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise HTTPError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise HTTPError(0, f"сеть недоступна: {exc.reason}") from exc
    return json.loads(raw) if raw else None
