"""JSON logging with request IDs for the API service.

Request IDs come from `asgi-correlation-id` and JSON lines from `python-json-logger`; the
access log is uvicorn's, written through the same formatter. Latency and route metrics
come from Prometheus in WP 12. There is no Starlette `BaseHTTPMiddleware`, which would
buffer streamed responses such as the agent thinking stream.
"""

from typing import Any

from pythonjsonlogger.core import RESERVED_ATTRS

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
