"""类型化错误族（spec §7）：失败显式、状态码明确，禁止静默兜底。"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    http_status = 400
    code = "app_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(AppError):
    http_status = 404
    code = "not_found"


class ValidationFailed(AppError):
    http_status = 422
    code = "validation_failed"


class Conflict(AppError):
    http_status = 409
    code = "conflict"


class LicenseViolation(AppError):
    """sources 注册表的 allowed_use 门禁被触发（spec §3）。"""

    http_status = 400
    code = "license_violation"


class NotConfigured(AppError):
    """依赖的外部配置缺失（如 LLM key）。启动可用、调用即失败，显式而非兜底。"""

    http_status = 503
    code = "not_configured"


class UpstreamError(AppError):
    """上游（LLM/采集源）调用失败。"""

    http_status = 502
    code = "upstream_error"


class StructuredOutputError(AppError):
    """LLM 结构化输出经单次重试仍未通过 schema 校验。"""

    http_status = 502
    code = "structured_output_failed"


class NotImplementedYet(AppError):
    """该能力属于后续交付阶段（spec §9），显式 501 而非假实现。"""

    http_status = 501
    code = "not_implemented_yet"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )
