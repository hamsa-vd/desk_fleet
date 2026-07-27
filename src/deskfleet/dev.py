"""Local development launcher for the API, mock API, and Streamlit UI."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class ServiceCommand:
    name: str
    command: tuple[str, ...]


#: Only correct for a source checkout (`src/deskfleet/dev.py`), which is what `uv run` gives you —
#: the project installs editable. A wheel install would resolve this into site-packages.
ROOT = Path(__file__).resolve().parents[2]

UI_PORT = "8501"

SERVICES: tuple[ServiceCommand, ...] = (
    ServiceCommand(
        name="mock_api",
        command=(sys.executable, "-m", "uvicorn", "mock_api.app:app", "--port", "8081"),
    ),
    ServiceCommand(
        name="deskfleet",
        command=(
            sys.executable,
            "-m",
            "uvicorn",
            "deskfleet.api.app:app",
            "--reload",
            "--port",
            "8080",
        ),
    ),
    ServiceCommand(
        name="streamlit",
        command=(
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/streamlit_app/main.py",
            "--server.port",
            UI_PORT,
        ),
    ),
)


def build_commands() -> tuple[ServiceCommand, ...]:
    return SERVICES


def _prefix_output(name: str, stream: TextIO) -> None:
    for line in stream:
        print(f"[{name}] {line}", end="", flush=True)


def _spawn(command: ServiceCommand) -> subprocess.Popen[str]:
    # Children write to a pipe, not a tty, so without this their output arrives in 8 kB bursts.
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen(
        command.command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def _terminate(processes: list[subprocess.Popen[str]]) -> None:
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    for proc in processes:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def main() -> int:
    processes: list[subprocess.Popen[str]] = []
    threads: list[threading.Thread] = []

    def shutdown(*_: object) -> None:
        _terminate(processes)
        raise SystemExit(130)

    previous_int = signal.signal(signal.SIGINT, shutdown)
    previous_term = signal.signal(signal.SIGTERM, shutdown)

    try:
        for service in SERVICES:
            proc = _spawn(service)
            processes.append(proc)
            assert proc.stdout is not None
            thread = threading.Thread(
                target=_prefix_output, args=(service.name, proc.stdout), daemon=True
            )
            thread.start()
            threads.append(thread)

        # These services are only useful together, so the first exit — clean or not — ends the lot.
        while True:
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    _terminate(processes)
                    return code
            time.sleep(0.2)
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        for thread in threads:
            thread.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
