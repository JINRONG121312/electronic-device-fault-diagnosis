"""Stable API routing boundary for the local dashboard server.

The frontend should depend on these route names through ``web/api_client.js``.
The HTTP server owns static-file concerns; this module owns API dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Callable


ApiResult = tuple[HTTPStatus, dict[str, Any]]
GetHandler = Callable[[dict[str, list[str]]], ApiResult]
PostHandler = Callable[[dict[str, Any]], ApiResult]


@dataclass(frozen=True)
class ApiRoutes:
    get: dict[str, GetHandler]
    post: dict[str, PostHandler]

    def handle_get(self, path: str, query: dict[str, list[str]]) -> ApiResult:
        handler = self.get.get(path)
        if handler is None:
            return HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown API endpoint."}
        return handler(query)

    def handle_post(self, path: str, body: dict[str, Any]) -> ApiResult:
        handler = self.post.get(path)
        if handler is None:
            return HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown API endpoint."}
        return handler(body)


def ok(data: dict[str, Any]) -> ApiResult:
    return HTTPStatus.OK, data


def api_error(status: HTTPStatus, message: str) -> ApiResult:
    return status, {"ok": False, "error": message}
