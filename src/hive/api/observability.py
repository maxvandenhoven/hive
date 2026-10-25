"""JSON logging and request IDs for the API service."""

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, override

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
"""The header that carries the request ID in requests and responses."""

REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
"""The ID of the request being handled, included in every log line written for it."""

IGNORED_LOG_RECORD_ATTRIBUTES = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
    | {"message", "asctime", "color_message"}
)
"""The attributes of every log record and the coloured message copy uvicorn adds, which
are left out of log lines; the remaining attributes are the `extra` fields of a call."""


class JsonLogFormatter(logging.Formatter):
    """Format log records as one JSON object per line.

    Every line has the `time`, `level`, `logger` and `message`, the request ID when the
    record was written while handling a request, the fields passed in `extra`, and the
    traceback in `exception` if there is one.
    """

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Format a record as a JSON object.

        Args:
            record: The log record.

        Returns:
            The JSON object on one line.
        """
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = REQUEST_ID.get()

        if request_id is not None:
            entry["request_id"] = request_id

        for key, value in vars(record).items():
            if key not in IGNORED_LOG_RECORD_ATTRIBUTES and not key.startswith("_"):
                entry[key] = value

        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


def logging_config(level: str) -> dict[str, Any]:
    """Build the `logging.config.dictConfig` configuration of the service.

    Passed to uvicorn, which applies it in every server process, including the one it
    starts for `--reload`.

    Args:
        level: The level of the root logger, for example `INFO`.

    Returns:
        A configuration that writes JSON lines to stderr, with the uvicorn loggers
        propagating to the root logger and the plugin setup of Alembic silenced.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": JsonLogFormatter}},
        "handlers": {"stderr": {"class": "logging.StreamHandler", "formatter": "json"}},
        "root": {"level": level, "handlers": ["stderr"]},
        "loggers": {
            **{
                name: {"handlers": [], "propagate": True}
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
            },
            "alembic.runtime.plugins": {"level": "WARNING"},
        },
    }


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Give every request an ID and log one line per request with its latency.

    The ID is taken from the `X-Request-ID` header, or generated, and returned in the
    same header of the response.
    """

    @override
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Handle a request with its ID set, then log it.

        Args:
            request: The incoming request.
            call_next: Handles the request in the rest of the app.

        Returns:
            The response, with the `X-Request-ID` header set.
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = REQUEST_ID.set(request_id)
        start = time.perf_counter()

        try:
            response = await call_next(request)
            route = request.scope.get("route")
            logger.info(
                "%s %s %d",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "route": getattr(route, "path", None),
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            response.headers[REQUEST_ID_HEADER] = request_id
        finally:
            REQUEST_ID.reset(token)

        return response
