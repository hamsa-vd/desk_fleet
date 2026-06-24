import json
import logging
from collections.abc import Callable

import pytest

from deskfleet.config import Settings, configure_logging, get_logger


def _last_record(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_emits_json_with_event_and_level(
    capsys: pytest.CaptureFixture[str], settings_factory: Callable[..., Settings]
) -> None:
    configure_logging(settings_factory())
    get_logger("deskfleet.test").info("ticket_started", extra={"ticket_id": "T-1"})

    record = _last_record(capsys)
    assert record["level"] == "INFO"
    assert record["event"] == "ticket_started"
    assert record["ticket_id"] == "T-1"


def test_secret_in_message_is_redacted(
    capsys: pytest.CaptureFixture[str], settings_factory: Callable[..., Settings]
) -> None:
    configure_logging(settings_factory())
    get_logger("deskfleet.test").info("calling provider with sk-abc123def456")

    assert "sk-abc123def456" not in json.dumps(_last_record(capsys))


def test_secret_in_extras_is_redacted(
    capsys: pytest.CaptureFixture[str], settings_factory: Callable[..., Settings]
) -> None:
    configure_logging(settings_factory())
    get_logger("deskfleet.test").warning(
        "auth_failed",
        extra={"api_key": "whatever-this-is", "trace": "lsv2_pt_9876543210"},
    )

    dumped = json.dumps(_last_record(capsys))
    assert "whatever-this-is" not in dumped
    assert "lsv2_pt_9876543210" not in dumped


def test_log_level_comes_from_settings(settings_factory: Callable[..., Settings]) -> None:
    configure_logging(settings_factory(log_level="WARNING"))

    assert logging.getLogger().level == logging.WARNING


def test_unknown_langchain_endpoint_warns_without_raising(
    capsys: pytest.CaptureFixture[str], settings_factory: Callable[..., Settings]
) -> None:
    configure_logging(settings_factory(langchain_endpoint="https://smith.example.com"))

    record = _last_record(capsys)
    assert record["level"] == "WARNING"
    assert record["event"] == "unrecognised_langchain_endpoint"
