from pathlib import Path
from types import SimpleNamespace
import subprocess

from hackster_studio.automation import dgx_services


class FakeResponse:
    status = 200

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_apply_model_profile_sets_env_from_config(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "profiles.yaml"
    config.write_text(
        """
profiles:
  image:
    draft:
      env:
        COMFYUI_WORKFLOW_KIND: flux
        COMFYUI_UNET: flux1-schnell.safetensors
      start_services: [comfyui.service]
      stop_services: [vllm-planner.service]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HACKSTER_DGX_MODEL_CONFIG", str(config))

    profile = dgx_services.apply_model_profile("image", "draft")

    assert profile.name == "draft"
    assert profile.start_services == ["comfyui.service"]
    assert profile.stop_services == ["vllm-planner.service"]
    assert profile.env["COMFYUI_UNET"] == "flux1-schnell.safetensors"
    assert dgx_services.os.getenv("COMFYUI_UNET") == "flux1-schnell.safetensors"


def test_prepare_dgx_planner_starts_profile_service_and_waits(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "profiles.yaml"
    config.write_text(
        """
profiles:
  planner:
    tiny:
      env:
        DGX_LLM_BASE_URL: http://dgx.example/v1
        DGX_LLM_MODEL: tiny-planner
      start_services: [vllm-tiny.service]
      stop_services: [comfyui-heavy.service]
      ready_url: http://dgx.example/v1/models
      ready_timeout_seconds: 2
      ready_interval_seconds: 0.01
""".strip()
        + "\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    opened: list[str] = []

    monkeypatch.setenv("HACKSTER_DGX_MANAGE_SERVICES", "1")
    monkeypatch.setenv("HACKSTER_DGX_MODEL_CONFIG", str(config))
    monkeypatch.setenv("HACKSTER_DGX_PLANNER_PROFILE", "tiny")
    monkeypatch.setattr(dgx_services.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(dgx_services.urllib.request, "urlopen", lambda request, timeout=10: opened.append(request.full_url) or FakeResponse())

    assert dgx_services.prepare_dgx_planner() is True

    assert calls == [
        ["ssh", "sync-spark-d1a9_local", "systemctl", "--user", "stop", "comfyui-heavy.service"],
        ["ssh", "sync-spark-d1a9_local", "systemctl", "--user", "start", "vllm-tiny.service"],
    ]
    assert opened == ["http://dgx.example/v1/models"]
    assert dgx_services.os.getenv("DGX_LLM_MODEL") == "tiny-planner"


def test_release_dgx_planner_for_images_switches_to_image_profile(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "profiles.yaml"
    config.write_text(
        """
profiles:
  image:
    production:
      env:
        COMFYUI_URL: http://dgx.example:8188
        COMFYUI_UNET: flux1-dev.safetensors
      stop_services: [vllm-planner.service, vllm-video.service]
      start_services: [comfyui.service]
      ready_url: http://dgx.example:8188/system_stats
      ready_timeout_seconds: 2
      ready_interval_seconds: 0.01
""".strip()
        + "\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    opened: list[str] = []

    monkeypatch.setenv("HACKSTER_DGX_MANAGE_SERVICES", "1")
    monkeypatch.setenv("HACKSTER_DGX_MODEL_CONFIG", str(config))
    monkeypatch.setenv("HACKSTER_DGX_IMAGE_PROFILE", "production")
    monkeypatch.setattr(dgx_services.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(dgx_services.urllib.request, "urlopen", lambda request, timeout=10: opened.append(request.full_url) or FakeResponse())

    assert dgx_services.release_dgx_planner_for_images() is True

    assert calls == [
        ["ssh", "sync-spark-d1a9_local", "systemctl", "--user", "stop", "vllm-planner.service"],
        ["ssh", "sync-spark-d1a9_local", "systemctl", "--user", "stop", "vllm-video.service"],
        ["ssh", "sync-spark-d1a9_local", "systemctl", "--user", "start", "comfyui.service"],
    ]
    assert opened == ["http://dgx.example:8188/system_stats"]
    assert dgx_services.os.getenv("COMFYUI_UNET") == "flux1-dev.safetensors"


def test_stop_timeout_kills_and_resets_service(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[4] == "stop":
            raise subprocess.TimeoutExpired(cmd, timeout=1)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("HACKSTER_DGX_SERVICE_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(dgx_services.subprocess, "run", fake_run)

    dgx_services._run_systemctl("stop", "vllm-planner.service")

    assert calls == [
        ["ssh", "sync-spark-d1a9_local", "systemctl", "--user", "stop", "vllm-planner.service"],
        ["ssh", "sync-spark-d1a9_local", "systemctl", "--user", "kill", "-s", "SIGKILL", "vllm-planner.service"],
        ["ssh", "sync-spark-d1a9_local", "systemctl", "--user", "reset-failed", "vllm-planner.service"],
    ]


def test_read_dgx_planner_log_tails_configured_remote_file(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="vLLM planner log tail\nrequest running", stderr="")

    monkeypatch.setenv("HACKSTER_DGX_SSH_HOST", "dgx-test")
    monkeypatch.setenv("HACKSTER_DGX_VLLM_LOG", "/tmp/vllm.log")
    monkeypatch.setattr(dgx_services.subprocess, "run", fake_run)

    log_text = dgx_services.read_dgx_planner_log(lines=25)

    assert log_text == "vLLM planner log tail\nrequest running"
    assert calls == [["ssh", "dgx-test", "tail", "-n", "25", "/tmp/vllm.log"]]
