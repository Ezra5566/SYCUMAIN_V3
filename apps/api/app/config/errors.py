"""Standardized error response models."""

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Structured error response body."""

    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """API error envelope."""

    error: ErrorDetail


def make_error_response(
    code: str,
    message: str,
    request_id: str | None = None,
    status_code: int = 400,
) -> dict[str, Any]:
    """Build a consistent error dict for FastAPI responses."""
    return {
        "status_code": status_code,
        "content": ErrorResponse(
            error=ErrorDetail(code=code, message=message, request_id=request_id)
        ).model_dump(),
    }
