"""Application errors with a stable JSON shape."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, detail: Any = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        if code:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            body["detail"] = self.detail
        return {"error": body}


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"


class LLMError(AppError):
    status_code = 503
    code = "llm_unavailable"


class LLMNotConfigured(LLMError):
    code = "llm_not_configured"


class PdfError(AppError):
    status_code = 422
    code = "pdf_unreadable"


class ModuleUnavailable(AppError):
    status_code = 501
    code = "module_unavailable"
