import json
import logging
import logging.config
import sys
import uuid
from collections.abc import Generator

import httpx2
import pytest
from asgi_correlation_id import correlation_id

from hive.api.observability import logging_config

pytestmark = pytest.mark.anyio


def make_record(**extra: object) -> logging.LogRecord:
    """Build an info record from `hive.test` with the given extra fields."""
    record = logging.LogRecord("hive.test", logging.INFO, __file__, 1, "x=%d", (1,), None)
    record.__dict__.update(extra)

    return record


@pytest.fixture(scope="function")
def handler() -> Generator[logging.Handler]:
    """Apply the logging configuration and yield its handler; the root is restored."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level

    try:
        logging.config.dictConfig(logging_config("WARNING"))
        yield root.handlers[-1]
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


def format_json(handler: logging.Handler, record: logging.LogRecord) -> dict[str, object]:
    """Filter and format a record like the handler does, and parse the JSON line."""
    assert handler.filter(record)

    return json.loads(handler.format(record))


class TestLoggingConfig:
    def test_sets_root_level(self, handler: logging.Handler) -> None:
        assert logging.getLogger().level == logging.WARNING
        assert isinstance(handler, logging.StreamHandler)

    def test_formats_message_and_extra_fields(self, handler: logging.Handler) -> None:
        entry = format_json(handler=handler, record=make_record(game_id="g"))

        assert entry["level"] == "INFO"
        assert entry["logger"] == "hive.test"
        assert entry["message"] == "x=1"
        assert entry["game_id"] == "g"
        assert entry["request_id"] is None
        assert "time" in entry
        assert "args" not in entry

    def test_drops_uvicorn_color_message(self, handler: logging.Handler) -> None:
        entry = format_json(handler=handler, record=make_record(color_message="x"))

        assert "color_message" not in entry

    def test_includes_request_id(self, handler: logging.Handler) -> None:
        token = correlation_id.set("abc")

        try:
            entry = format_json(handler=handler, record=make_record())
        finally:
            correlation_id.reset(token)

        assert entry["request_id"] == "abc"

    def test_formats_uvicorn_access_lines(self, handler: logging.Handler) -> None:
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:1", "GET", "/healthz", "1.1", 200),
            None,
        )
        token = correlation_id.set("abc")

        try:
            entry = format_json(handler=handler, record=record)
        finally:
            correlation_id.reset(token)

        assert entry["logger"] == "uvicorn.access"
        assert entry["message"] == '127.0.0.1:1 - "GET /healthz HTTP/1.1" 200'
        assert entry["request_id"] == "abc"

    def test_includes_exception(self, handler: logging.Handler) -> None:
        msg = "boom"

        try:
            raise ValueError(msg)
        except ValueError:
            record = make_record()
            record.exc_info = sys.exc_info()

        entry = format_json(handler=handler, record=record)

        assert "ValueError: boom" in str(entry["exception"])


async def test_request_id_is_returned(offline_client: httpx2.AsyncClient) -> None:
    request_id = uuid.uuid4().hex
    given = await offline_client.get("/healthz", headers={"X-Request-ID": request_id})
    invalid = await offline_client.get("/healthz", headers={"X-Request-ID": "x\ny"})
    generated = await offline_client.get("/healthz")

    assert given.headers["X-Request-ID"] == request_id
    assert len(invalid.headers["X-Request-ID"]) == 32
    assert len(generated.headers["X-Request-ID"]) == 32
