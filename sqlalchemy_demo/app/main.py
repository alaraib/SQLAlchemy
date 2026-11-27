from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import re
import time
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.engine import Engine

from app.db import models
from app.db.database import Base, engine
from app.errors import DeviceNotFoundError, DuplicateDeviceError
from app.api.routes import router
from app.logging_config import configure_logging, safe_device_id


_safe_request_id = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
logger = structlog.get_logger("netpulse.request")


def create_app(database_engine: Engine = engine) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        Base.metadata.create_all(bind=database_engine)
        yield

    application = FastAPI(lifespan=lifespan)

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        start = time.perf_counter()
        structlog.contextvars.clear_contextvars()
        supplied_id = request.headers.get("X-Request-ID")
        request_id = (
            supplied_id
            if supplied_id is not None and _safe_request_id.fullmatch(supplied_id)
            else uuid4().hex
        )
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as error:
            logger.exception("request_failed", error_type=type(error).__name__)
            raise
        finally:
            try:
                route = request.scope.get("route")
                logger.info(
                    "request_completed",
                    method=request.method,
                    path=getattr(route, "path", request.url.path),
                    status_code=status_code,
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
            finally:
                structlog.contextvars.clear_contextvars()

    application.include_router(router)

    @application.exception_handler(DuplicateDeviceError)
    async def duplicate_device_handler(
        _, error: DuplicateDeviceError
    ) -> JSONResponse:
        device_id = error.args[0] if error.args and isinstance(error.args[0], str) else ""
        logger.warning(
            "domain_error", error_type=type(error).__name__,
            device_id=safe_device_id(device_id),
        )
        return JSONResponse(
            status_code=409,
            content={"detail": f"Device '{error}' already exists"},
        )

    @application.exception_handler(DeviceNotFoundError)
    async def missing_device_handler(
        _, error: DeviceNotFoundError
    ) -> JSONResponse:
        device_id = error.args[0] if error.args and isinstance(error.args[0], str) else ""
        logger.warning(
            "domain_error", error_type=type(error).__name__,
            device_id=safe_device_id(device_id),
        )
        return JSONResponse(
            status_code=404,
            content={"detail": f"Device '{error}' not found"},
        )

    @application.exception_handler(Exception)
    async def server_error_handler(request: Request, _: Exception) -> PlainTextResponse:
        request_id = getattr(request.state, "request_id", None)
        headers = {"X-Request-ID": request_id} if request_id else None
        return PlainTextResponse("Internal Server Error", status_code=500, headers=headers)

    return application


app = create_app()
