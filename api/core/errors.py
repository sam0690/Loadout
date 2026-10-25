"""Domain failures, and the one place they become status codes.

Services raise these and never name a status. The body is `{"detail": ...}`, the same
shape HTTPException produced when the routes raised it directly, so clients see no change.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code: int

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class Unauthorized(DomainError):
    status_code = 401


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class Invalid(DomainError):
    status_code = 422


async def _handle(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def register(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _handle)
