"""JSON logging, request IDs and access logs for the API service.

Request IDs come from `asgi-correlation-id` and JSON lines from `python-json-logger`. Both
middlewares here are plain ASGI rather than Starlette's `BaseHTTPMiddleware`, so streamed
responses such as the agent thinking stream pass through unbuffered.
"""

import logging
import time
from typing import Any

from pythonjsonlogger.core import RESERVED_ATTRS
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
"""The header that carries the request ID in requests and responses."""

LOG_RECORD_IGNORED_ATTRIBUTES = [*RESERVED_ATTRS, "color_message"]
"""The record attributes left out of log lines: the standard ones, which the format
names explicitly, and the coloured message copy uvicorn adds. The remaining attributes are
the `extra` fields of a call."""


def logging_config(level: str) -> dict[str, Any]:
    """Build the `logging.config.dictConfig` configuration of the service.

    Passed to uvicorn, which applies it in every server process, including the one it
    starts for `--reload`. Every line is a JSON object with the `time`, `level`, `logger`,
    `message` and `request_id` (`null` outside a request), the `extra` fields of the call,
    and the traceback in `exception` if there is one.

    Args:
        level: The level of the root logger, for example `INFO`.

    Returns:
        A configuration that writes JSON lines to stderr, with the uvicorn loggers
        propagating to the root logger and the plugin setup of Alembic silenced.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": "asgi_correlation_id.CorrelationIdFilter"}},
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.json.JsonFormatter",
                "fmt": "%(levelname)s %(name)s %(message)s %(correlation_id)s",
                "rename_fields": {
                    "levelname": "level",
                    "name": "logger",
                    "correlation_id": "request_id",
                    "exc_info": "exception",
                },
                "reserved_attrs": LOG_RECORD_IGNORED_ATTRIBUTES,
                "timestamp": "time",
            }
        },
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "filters": ["request_id"],
            }
        },
        "root": {"level": level, "handlers": ["stderr"]},
        "loggers": {
            **{
                name: {"handlers": [], "propagate": True}
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
            },
            "alembic.runtime.plugins": {"level": "WARNING"},
        },
    }


class AccessLogMiddleware:
    """Log one line per request with its route, status and latency.

    The line is written when the response is complete, so for a stream the latency is
    the time until the stream ended.

    Attributes:
        app: The wrapped ASGI app.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap an app.

        Args:
            app: The ASGI app.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle a request, then log it.

        Args:
            scope: The connection scope.
            receive: Receives messages from the client.
            send: Sends messages to the client.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500

        async def send_and_record_status(message: Message) -> None:
            """Send a message, noting the status code of the response.

            Args:
                message: The ASGI message.
            """
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]

            await send(message)

        try:
            await self.app(scope, receive, send_and_record_status)
        finally:
            route = scope.get("route")
            logger.info(
                "%s %s %d",
                scope["method"],
                scope["path"],
                status_code,
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "route": getattr(route, "path", None),
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
