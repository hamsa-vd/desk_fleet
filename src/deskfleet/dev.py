"""Local development launcher for the API, mock API, and Streamlit UI."""

from __future__ import annotations

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


ROOT = Path(__file__).resolve().parents[2]

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
        command=(sys.executable, "-m", "streamlit", "run", "src/streamlit_app/main.py"),
    ),
)


def build_commands() -> tuple[ServiceCommand, ...]:
    return SERVICES


def _prefix_output(name: str, stream: TextIO) -> None:
    for line in stream:
        print(f"[{name}] {line}", end="", flush=True)


def _spawn(command: ServiceCommand) -> subprocess.Popen[str]:
    return subprocess.Popen(
        command.command,
        cwd=ROOT,
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

        while processes:
            for proc in list(processes):
                code = proc.poll()
                if code is None:
                    continue
                if code != 0:
                    _terminate(processes)
                    return code
                _terminate(processes)
                return code
            time.sleep(0.2)
        return 0
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        for thread in threads:
            thread.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
