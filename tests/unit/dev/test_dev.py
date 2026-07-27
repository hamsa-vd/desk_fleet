"""The launcher is driven with real child processes — what is worth testing here is process
lifecycle, and a mocked Popen would only assert the mock."""

from __future__ import annotations

import signal
import subprocess
import sys
import time

import pytest

from deskfleet import dev
from deskfleet.dev import ServiceCommand, build_commands


def _script(body: str) -> tuple[str, ...]:
    return (sys.executable, "-c", body)


@pytest.fixture
def fake_services(monkeypatch: pytest.MonkeyPatch):
    """Swap the three real services for scripts whose exit behaviour a test dictates."""

    def _install(*bodies: str) -> None:
        monkeypatch.setattr(
            dev,
            "SERVICES",
            tuple(
                ServiceCommand(name=f"svc{index}", command=_script(body))
                for index, body in enumerate(bodies)
            ),
        )

    return _install


def test_the_launcher_defines_the_three_expected_commands() -> None:
    commands = build_commands()

    assert [service.name for service in commands] == ["mock_api", "deskfleet", "streamlit"]
    assert commands[0].command[-2:] == ("--port", "8081")
    assert commands[1].command[-2:] == ("--port", "8080")
    assert commands[2].command[1:5] == ("-m", "streamlit", "run", "src/streamlit_app/main.py")
    assert commands[2].command[-2:] == ("--server.port", dev.UI_PORT)


def test_the_working_directory_holds_what_the_commands_reference() -> None:
    assert (dev.ROOT / "src" / "streamlit_app" / "main.py").is_file()
    assert (dev.ROOT / "pyproject.toml").is_file()


def test_a_failing_service_brings_the_others_down_and_returns_its_code(fake_services) -> None:
    fake_services("import sys; sys.exit(3)", "import time; time.sleep(60)")

    assert dev.main() == 3


def test_a_clean_exit_also_stops_the_stack(fake_services) -> None:
    fake_services("pass", "import time; time.sleep(60)")

    assert dev.main() == 0


def test_child_output_is_prefixed_with_the_service_name(
    fake_services, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_services("print('listening on 8081')")

    dev.main()

    assert "[svc0] listening on 8081" in capsys.readouterr().out


def test_terminate_kills_a_child_that_ignores_sigterm() -> None:
    stubborn = subprocess.Popen(
        _script(
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
        ),
        stdout=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.3)  # Let the handler install, or the SIGTERM lands first and proves nothing.

    dev._terminate([stubborn])

    assert stubborn.poll() is not None


def test_the_signal_handlers_are_restored_after_a_run(fake_services) -> None:
    before = signal.getsignal(signal.SIGINT)
    fake_services("pass")

    dev.main()

    assert signal.getsignal(signal.SIGINT) is before
