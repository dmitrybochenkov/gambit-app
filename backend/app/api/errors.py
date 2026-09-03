from dataclasses import dataclass

from fastapi import Request, status
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        },
    )


def api_error(status_code: int, code: str, message: str) -> ApiError:
    return ApiError(status_code=status_code, code=code, message=message)


def unauthorized(message: str = "Unauthorized") -> ApiError:
    return api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized", message)


def forbidden(message: str = "Forbidden") -> ApiError:
    return api_error(status.HTTP_403_FORBIDDEN, "forbidden", message)


def not_found(message: str = "Not found") -> ApiError:
    return api_error(status.HTTP_404_NOT_FOUND, "not_found", message)


def validation_error(message: str = "Validation error") -> ApiError:
    return api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error", message)


def conflict(message: str = "Conflict") -> ApiError:
    return api_error(status.HTTP_409_CONFLICT, "conflict", message)
