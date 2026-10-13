"""RFC 7807 application/problem+json errors."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM = "application/problem+json"


class Problem(Exception):
    def __init__(
        self, status: int, title: str, detail: str | None = None, **extra: Any
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra


def _body(status: int, title: str, detail: str | None, instance: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status, "instance": instance}
    if detail:
        body["detail"] = detail
    body.update(extra)
    return body


def install(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> JSONResponse:
        headers = {}
        if "retry_after" in exc.extra:
            headers["Retry-After"] = str(exc.extra["retry_after"])
        return JSONResponse(
            _body(exc.status, exc.title, exc.detail, request.url.path, **exc.extra),
            status_code=exc.status,
            media_type=PROBLEM,
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            _body(exc.status_code, str(exc.detail), None, request.url.path),
            status_code=exc.status_code,
            media_type=PROBLEM,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        detail = "Request did not match the schema."
        return JSONResponse(
            _body(422, "Validation error", detail, request.url.path, errors=errors),
            status_code=422,
            media_type=PROBLEM,
        )
