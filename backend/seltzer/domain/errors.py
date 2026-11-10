"""Domain errors, rendered as application/problem+json by the API."""

from __future__ import annotations

from typing import Any


class Problem(Exception):
    status = 400
    title = "Bad request"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.extra = extra

    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"type": "about:blank", "title": self.title, "status": self.status}
        if self.detail:
            body["detail"] = self.detail
        body.update(self.extra)
        return body


class Invalid(Problem):
    status = 422
    title = "Invalid request"


class Unauthorized(Problem):
    status = 401
    title = "Not signed in"


class Forbidden(Problem):
    status = 403
    title = "Not allowed"


class NotFound(Problem):
    status = 404
    title = "Not found"


class Conflict(Problem):
    """The write doesn't fit the current state. `current` carries what the client should show."""

    status = 409
    title = "Conflict"


class TooLarge(Problem):
    status = 413
    title = "Too large"
