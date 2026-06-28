from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from schemas.errors import ERROR_CODES
import logging

logger = logging.getLogger("middleware.error_handler")

def raise_api_error(code: str, message: str, fallback_used: bool = False):
    status_code = ERROR_CODES.get(code, 400)
    raise StarletteHTTPException(
        status_code=status_code,
        detail=message,
        headers={"X-Error-Code": code, "X-Fallback-Used": str(fallback_used).lower()}
    )

def add_exception_handlers(app: FastAPI):
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "MISSING_PARAMS",
                    "message": f"Validation error: {exc.errors()}",
                    "fallback_used": False
                }
            }
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        code = exc.headers.get("X-Error-Code", "HTTP_ERROR") if exc.headers else "HTTP_ERROR"
        fallback_used = exc.headers.get("X-Fallback-Used", "false").lower() == "true" if exc.headers else False
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": str(exc.detail),
                    "fallback_used": fallback_used
                }
            }
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred. Please try again.",
                    "fallback_used": False
                }
            }
        )
