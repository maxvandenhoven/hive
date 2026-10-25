import json
import logging
import logging.config
import sys

import pytest
from fastapi.testclient import TestClient

from hive.api.observability import REQUEST_ID, JsonLogFormatter, logging_config


def make_record(**extra: object) -> logging.LogRecord:
    """Build an info record from `hive.test` with the given extra fields."""
    record = logging.LogRecord("hive.test", logging.INFO, __file__, 1, "x=%d", (1,), None)
    record.__dict__.update(extra)

    return record


class TestJsonLogFormatter:
    def test_formats_message_and_extra_fields(self) -> None:
        entry = json.loads(JsonLogFormatter().format(make_record(game_id="g")))

        assert entry["level"] == "INFO"
        assert entry["logger"] == "hive.test"
        assert entry["message"] == "x=1"
        assert entry["game_id"] == "g"
        assert "request_id" not in entry
        assert "args" not in entry

    def test_includes_request_id(self) -> None:
        token = REQUEST_ID.set("abc")

        try:
            entry = json.loads(JsonLogFormatter().format(make_record()))
        finally:
            REQUEST_ID.reset(token)

        assert entry["request_id"] == "abc"

    def test_includes_exception(self) -> None:
        msg = "boom"

        try:
            raise ValueError(msg)
        except ValueError:
            record = make_record()
            record.exc_info = sys.exc_info()

        entry = json.loads(JsonLogFormatter().format(record))

        assert "ValueError: boom" in entry["exception"]


def test_logging_config_is_valid() -> None:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level

    try:
        logging.config.dictConfig(logging_config("WARNING"))

        assert root.level == logging.WARNING
        assert isinstance(root.handlers[-1].formatter, JsonLogFormatter)
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


def test_logs_one_line_per_request(
    offline_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="hive.api.observability"):
        offline_client.get("/healthz", headers={"X-Request-ID": "abc"})

    [record] = caplog.records
    assert record.getMessage() == "GET /healthz 200"
    assert record.__dict__["route"] == "/healthz"
    assert record.__dict__["status"] == 200
    assert record.__dict__["duration_ms"] >= 0
