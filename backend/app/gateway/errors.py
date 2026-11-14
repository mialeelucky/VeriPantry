"""RFC 9457 problem details (trust-protocol §4.4)."""

from __future__ import annotations

from typing import Any

PROBLEM_BASE = "https://api.veripantry.example/problems/"


class ApiError(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str | None = None, **extra: Any):
        super().__init__(detail or title)
        self.status, self.code, self.title, self.detail, self.extra = status, code, title, detail, extra

    def problem(self) -> dict[str, Any]:
        body = {"type": PROBLEM_BASE + self.code.replace("_", "-"), "title": self.title, "status": self.status}
        if self.detail:
            body["detail"] = self.detail
        body.update(self.extra)
        return body
