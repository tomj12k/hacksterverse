"""DGX model/service handoff helpers for planner and image phases."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from typing import Protocol

import yaml

from ..config import PROJECT_ROOT


class ConsoleLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


TRUTHY = {"1", "true", "yes", "on"}
DEFAULT_PROFILE_CONFIG = PROJECT_ROOT / "configs" / "dgx_model_profiles.yaml"


@dataclass(frozen=True)
class DGXModelProfile:
    role: str
    name: str
    env: dict[str, str] = field(default_factory=dict)
    start_services: list[str] = field(default_factory=list)
    stop_services: list[str] = field(default_factory=list)
    ready_url: str = ""
    ready_timeout_seconds: int | None = None
    ready_interval_seconds: float | None = None


def dgx_service_management_enabled() -> bool:
    return os.getenv("HACKSTER_DGX_MANAGE_SERVICES", "").strip().lower() in TRUTHY


def apply_model_profile(role: str, profile_name: str | None = None, *, console: ConsoleLike | None = None) -> DGXModelProfile:
    """Apply env values for a configured DGX model profile."""
    profile = load_model_profile(role, profile_name)
    for key, value in profile.env.items():
        os.environ[key] = value
    if console and profile.env:
        console.print(f"[cyan]DGX:[/cyan] loaded {role} model profile {profile.name}")
    return profile


def prepare_dgx_planner(console: ConsoleLike | None = None) -> bool:
    """Start vLLM for DGX planning and wait for its OpenAI-compatible API."""
    if not dgx_service_management_enabled():
        return False
    profile = apply_model_profile("planner", os.getenv("HACKSTER_DGX_PLANNER_PROFILE"), console=console)
    for service in profile.stop_services:
        _run_systemctl("stop", service, console=console)
    for service in _planner_start_services(profile):
        _run_systemctl("start", service, console=console)
    _wait_for_url(
        _planner_ready_url(profile),
        timeout_seconds=_planner_ready_timeout(profile),
        interval_seconds=profile.ready_interval_seconds or _env_float("HACKSTER_DGX_PLANNER_READY_INTERVAL_SECONDS", 5.0),
        api_key=os.getenv("DGX_LLM_API_KEY", ""),
        console=console,
        label="planner API",
    )
    return True


def release_dgx_planner_for_images(console: ConsoleLike | None = None) -> bool:
    """Switch the DGX to the image profile so ComfyUI/FLUX can reclaim GPU memory."""
    if not dgx_service_management_enabled():
        return False
    profile = apply_model_profile("image", os.getenv("HACKSTER_DGX_IMAGE_PROFILE"), console=console)
    for service in _image_stop_services(profile):
        _run_systemctl("stop", service, console=console)
    for service in _image_start_services(profile):
        _run_systemctl("start", service, console=console)
    ready_url = profile.ready_url or _comfyui_ready_url()
    if ready_url:
        _wait_for_url(
            ready_url,
            timeout_seconds=profile.ready_timeout_seconds or _env_int("HACKSTER_DGX_IMAGE_READY_TIMEOUT_SECONDS", 180),
            interval_seconds=profile.ready_interval_seconds or _env_float("HACKSTER_DGX_IMAGE_READY_INTERVAL_SECONDS", 3.0),
            console=console,
            label="image API",
        )
    return True


def read_dgx_planner_log(*, lines: int = 80) -> str:
    """Read the recent DGX vLLM planner log over SSH for browser status displays."""
    host = os.getenv("HACKSTER_DGX_SSH_HOST", "sync-spark-d1a9_local")
    log_path = os.getenv("HACKSTER_DGX_VLLM_LOG", "/home/pizzacat/ai/logs/vllm-planner.log")
    safe_lines = max(10, min(400, int(lines or 80)))
    timeout = int(os.getenv("HACKSTER_DGX_LOG_TIMEOUT_SECONDS", "8"))
    result = subprocess.run(
        ["ssh", host, "tail", "-n", str(safe_lines), log_path],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Could not read DGX planner log: {details}")
    return result.stdout.strip()


def load_model_profile(role: str, profile_name: str | None = None) -> DGXModelProfile:
    role = role.strip().lower()
    name = (profile_name or os.getenv(f"HACKSTER_DGX_{role.upper()}_PROFILE") or _default_profile_name(role)).strip()
    profiles = _read_profiles()
    raw = _profile_payload(profiles, role, name)
    env = {str(key): str(value) for key, value in dict(raw.get("env", {})).items()}
    return DGXModelProfile(
        role=role,
        name=name,
        env=env,
        start_services=_string_list(raw.get("start_services")),
        stop_services=_string_list(raw.get("stop_services")),
        ready_url=str(raw.get("ready_url") or ""),
        ready_timeout_seconds=_optional_int(raw.get("ready_timeout_seconds")),
        ready_interval_seconds=_optional_float(raw.get("ready_interval_seconds")),
    )


def _run_systemctl(action: str, service: str, *, console: ConsoleLike | None = None) -> None:
    host = os.getenv("HACKSTER_DGX_SSH_HOST", "sync-spark-d1a9_local")
    timeout = int(os.getenv("HACKSTER_DGX_SERVICE_TIMEOUT_SECONDS", "120"))
    command = ["ssh", host, "systemctl", "--user", action, service]
    if console:
        console.print(f"[cyan]DGX:[/cyan] systemctl --user {action} {service}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        if action == "stop" and os.getenv("HACKSTER_DGX_FORCE_KILL_ON_STOP_TIMEOUT", "1").strip().lower() in TRUTHY:
            if console:
                console.print(f"[yellow]DGX:[/yellow] stop timed out for {service}; sending SIGKILL")
            _kill_service(host, service, timeout=timeout)
            return
        raise RuntimeError(f"DGX service {action} timed out for {service}.") from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"DGX service {action} failed for {service}: {details}")


def _kill_service(host: str, service: str, *, timeout: int) -> None:
    for args in (
        ["systemctl", "--user", "kill", "-s", "SIGKILL", service],
        ["systemctl", "--user", "reset-failed", service],
    ):
        result = subprocess.run(["ssh", host, *args], capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"DGX service kill fallback failed for {service}: {details}")


def _wait_for_url(
    url: str,
    *,
    timeout_seconds: int,
    interval_seconds: float,
    api_key: str = "",
    console: ConsoleLike | None = None,
    label: str = "DGX API",
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    if console:
        console.print(f"[cyan]DGX:[/cyan] waiting for {label} at {url}")
    while time.monotonic() < deadline:
        request = urllib.request.Request(url)
        if api_key:
            request.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if 200 <= response.status < 300:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(interval_seconds)
    raise TimeoutError(f"Timed out waiting for {label} at {url}. Last error: {last_error}")


def _read_profiles() -> dict[str, Any]:
    path = Path(os.getenv("HACKSTER_DGX_MODEL_CONFIG", str(DEFAULT_PROFILE_CONFIG))).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profiles = payload.get("profiles", payload)
    return profiles if isinstance(profiles, dict) else {}


def _profile_payload(profiles: dict[str, Any], role: str, name: str) -> dict[str, Any]:
    role_profiles = profiles.get(role, {})
    if isinstance(role_profiles, dict) and isinstance(role_profiles.get(name), dict):
        return dict(role_profiles[name])
    dotted = profiles.get(f"{role}.{name}", {})
    if isinstance(dotted, dict):
        return dict(dotted)
    return _fallback_profile(role, name)


def _fallback_profile(role: str, name: str) -> dict[str, Any]:
    if role == "planner":
        return {
            "env": {
                "DGX_LLM_BASE_URL": os.getenv("DGX_LLM_BASE_URL", "http://192.168.68.136:8000/v1"),
                "DGX_LLM_MODEL": os.getenv("DGX_LLM_MODEL", "Qwen3-32B-AWQ"),
            },
            "start_services": [os.getenv("HACKSTER_DGX_VLLM_SERVICE", "vllm-planner.service")],
            "ready_url": _planner_default_ready_url(),
        }
    if role == "image":
        return {
            "env": {},
            "start_services": _split_services(os.getenv("HACKSTER_DGX_IMAGE_START_SERVICES", "comfyui.service")),
            "stop_services": _split_services(
                os.getenv("HACKSTER_DGX_IMAGE_STOP_SERVICES", os.getenv("HACKSTER_DGX_VLLM_SERVICE", "vllm-planner.service"))
            ),
            "ready_url": _comfyui_ready_url(),
        }
    return {"env": {}, "start_services": [], "stop_services": []}


def _default_profile_name(role: str) -> str:
    if role == "planner":
        return "qwen3_32b_awq"
    if role == "image":
        return "flux_dev"
    return "default"


def _planner_start_services(profile: DGXModelProfile) -> list[str]:
    return profile.start_services or _split_services(os.getenv("HACKSTER_DGX_PLANNER_START_SERVICES", os.getenv("HACKSTER_DGX_VLLM_SERVICE", "vllm-planner.service")))


def _image_start_services(profile: DGXModelProfile) -> list[str]:
    return profile.start_services or _split_services(os.getenv("HACKSTER_DGX_IMAGE_START_SERVICES", "comfyui.service"))


def _image_stop_services(profile: DGXModelProfile) -> list[str]:
    return profile.stop_services or _split_services(os.getenv("HACKSTER_DGX_IMAGE_STOP_SERVICES", os.getenv("HACKSTER_DGX_VLLM_SERVICE", "vllm-planner.service")))


def _planner_ready_url(profile: DGXModelProfile) -> str:
    return profile.ready_url or _planner_default_ready_url()


def _planner_default_ready_url() -> str:
    return f"{(os.getenv('DGX_LLM_BASE_URL') or 'http://192.168.68.136:8000/v1').rstrip('/')}/models"


def _planner_ready_timeout(profile: DGXModelProfile) -> int:
    return profile.ready_timeout_seconds or _env_int("HACKSTER_DGX_PLANNER_READY_TIMEOUT_SECONDS", 600)


def _comfyui_ready_url() -> str:
    base_url = (os.getenv("COMFYUI_URL") or "http://192.168.68.136:8188").rstrip("/")
    return f"{base_url}/system_stats"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_services(value)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _split_services(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))
