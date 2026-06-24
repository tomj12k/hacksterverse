"""Shared pytest fixtures for the HacksterNiko test suite."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import pytest


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except (ConnectionRefusedError, TimeoutError, OSError):
            time.sleep(0.1)
    return False


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory):
    """Start a real uvicorn server on port 18765 for integration and browser tests."""
    port = 18_765
    env = os.environ.copy()
    env["HACKSTER_SCENE_ROOT"] = str(tmp_path_factory.mktemp("storybook_scenes"))
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "hackster_studio.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    if not _wait_for_port("127.0.0.1", port):
        proc.terminate()
        pytest.skip("Could not start live server within 15 s")

    yield f"http://127.0.0.1:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# pytest-playwright reads this fixture name for browser tests
@pytest.fixture(scope="session")
def base_url(live_server: str) -> str:
    return live_server
