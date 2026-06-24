"""ComfyUI API backend for local/LAN image generation."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PIL import Image


def generate_image_comfyui(
    prompt: str,
    output_path: Path,
    *,
    comfyui_url: str | None = None,
    workflow_path: Path | None = None,
    timeout_seconds: int | None = None,
) -> Path:
    """Submit a prompt to ComfyUI, poll for completion, and save the output PNG."""
    load_dotenv()
    base_url = (comfyui_url or os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
    timeout = timeout_seconds or int(os.getenv("COMFYUI_TIMEOUT_SECONDS", "1800"))
    workflow = load_workflow(workflow_path)
    reference_image_name = upload_reference_image_if_needed(base_url, workflow)
    workflow = prepare_workflow(workflow, prompt, output_path, reference_image_name=reference_image_name)

    prompt_id = submit_prompt(base_url, workflow)
    image_bytes = wait_for_image(base_url, prompt_id, timeout_seconds=timeout)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    set_dpi_metadata(output_path, int(os.getenv("COMFYUI_DPI", "300")))
    return output_path


def set_dpi_metadata(image_path: Path, dpi: int) -> None:
    """Attach print DPI metadata without changing image dimensions."""
    with Image.open(image_path) as image:
        image.save(image_path, dpi=(dpi, dpi))


def load_workflow(workflow_path: Path | None = None) -> dict[str, Any]:
    """Load a ComfyUI API workflow, or return a built-in workflow."""
    workflow_env = os.getenv("COMFYUI_WORKFLOW_PATH")
    path = workflow_path or (Path(workflow_env).expanduser() if workflow_env else None)
    if path:
        if not path.exists():
            raise FileNotFoundError(f"COMFYUI workflow JSON not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
    workflow_kind = os.getenv("COMFYUI_WORKFLOW_KIND", "flux").lower()
    if workflow_kind == "sdxl":
        return default_sdxl_workflow()
    if workflow_kind in {"flux_pulid", "pulid_flux"}:
        return default_flux_pulid_workflow()
    return default_flux_workflow()


def prepare_workflow(
    workflow: dict[str, Any],
    prompt: str,
    output_path: Path,
    *,
    reference_image_name: str | None = None,
) -> dict[str, Any]:
    workflow = deepcopy(workflow)
    positive_replaced = False
    negative_prompt = os.getenv(
        "COMFYUI_NEGATIVE_PROMPT",
        (
            "text, letters, words, captions, speech bubbles, labels, signs, numerals, glyphs, code symbols, "
            "fake writing, pseudo text, title typography, page numbers, manuscript, document, paper sheet, "
            "white page, columns of text, UI, panels, split page, worksheet, poster, watermark, logo, "
            "grid, gridlines, halftone, screen-door texture, moire pattern, mouth, frown, smile, nose, "
            "dangling cord, cable, leash, rope, strap, tail, tail-like shape, robot child, human child, "
            "mascot, flat vector art, simple sticker art, "
            "clipart, scary imagery, realistic weapons"
        ),
    )

    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") not in {"CLIPTextEncode", "CLIPTextEncodeFlux"}:
            continue
        title = str(node.get("_meta", {}).get("title", "")).lower()
        inputs = node.setdefault("inputs", {})
        if node.get("class_type") == "CLIPTextEncodeFlux":
            if "negative" in title:
                inputs["clip_l"] = negative_prompt
                inputs["t5xxl"] = negative_prompt
            elif "positive" in title or not positive_replaced:
                inputs["clip_l"] = prompt
                inputs["t5xxl"] = prompt
                positive_replaced = True
        else:
            if "negative" in title:
                inputs["text"] = negative_prompt
            elif "positive" in title or not positive_replaced:
                inputs["text"] = prompt
                positive_replaced = True

    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        inputs = node.setdefault("inputs", {})
        if class_type == "CheckpointLoaderSimple":
            inputs["ckpt_name"] = os.getenv("COMFYUI_CHECKPOINT", inputs.get("ckpt_name", "sd_xl_base_1.0.safetensors"))
        elif class_type == "UNETLoader":
            inputs["unet_name"] = os.getenv("COMFYUI_UNET", inputs.get("unet_name", "flux1-schnell.safetensors"))
            inputs["weight_dtype"] = os.getenv("COMFYUI_UNET_DTYPE", inputs.get("weight_dtype", "fp8_e4m3fn"))
        elif class_type == "DualCLIPLoader":
            inputs["clip_name1"] = os.getenv("COMFYUI_CLIP_1", inputs.get("clip_name1", "clip_l.safetensors"))
            inputs["clip_name2"] = os.getenv("COMFYUI_CLIP_2", inputs.get("clip_name2", "t5xxl_fp16.safetensors"))
            inputs["type"] = os.getenv("COMFYUI_CLIP_TYPE", inputs.get("type", "flux"))
        elif class_type == "VAELoader":
            inputs["vae_name"] = os.getenv("COMFYUI_VAE", inputs.get("vae_name", "ae.safetensors"))
        elif class_type == "LoraLoader":
            lora_name = os.getenv("COMFYUI_LORA_NAME")
            if lora_name:
                inputs["lora_name"] = lora_name
            inputs["strength_model"] = float(os.getenv("COMFYUI_LORA_STRENGTH_MODEL", str(inputs.get("strength_model", 0.85))))
            inputs["strength_clip"] = float(os.getenv("COMFYUI_LORA_STRENGTH_CLIP", str(inputs.get("strength_clip", 0.85))))
        elif class_type == "EmptyLatentImage":
            inputs["width"] = int(os.getenv("COMFYUI_GENERATION_WIDTH", os.getenv("COMFYUI_WIDTH", str(inputs.get("width", 1024)))))
            inputs["height"] = int(os.getenv("COMFYUI_GENERATION_HEIGHT", os.getenv("COMFYUI_HEIGHT", str(inputs.get("height", 1024)))))
        elif class_type == "ModelSamplingFlux":
            inputs["width"] = int(os.getenv("COMFYUI_GENERATION_WIDTH", os.getenv("COMFYUI_WIDTH", str(inputs.get("width", 1024)))))
            inputs["height"] = int(os.getenv("COMFYUI_GENERATION_HEIGHT", os.getenv("COMFYUI_HEIGHT", str(inputs.get("height", 1024)))))
            inputs["max_shift"] = float(os.getenv("COMFYUI_FLUX_MAX_SHIFT", str(inputs.get("max_shift", 1.15))))
            inputs["base_shift"] = float(os.getenv("COMFYUI_FLUX_BASE_SHIFT", str(inputs.get("base_shift", 0.5))))
        elif class_type == "FluxGuidance":
            inputs["guidance"] = float(os.getenv("COMFYUI_FLUX_GUIDANCE", str(inputs.get("guidance", 3.5))))
        elif class_type == "KSampler":
            inputs["seed"] = int(os.getenv("COMFYUI_SEED", str(random.randint(1, 2**31 - 1))))
            inputs["steps"] = int(os.getenv("COMFYUI_STEPS", str(inputs.get("steps", 30))))
            inputs["cfg"] = float(os.getenv("COMFYUI_CFG", str(inputs.get("cfg", 7))))
            inputs["sampler_name"] = os.getenv("COMFYUI_SAMPLER", inputs.get("sampler_name", "euler"))
            inputs["scheduler"] = os.getenv("COMFYUI_SCHEDULER", inputs.get("scheduler", "normal"))
        elif class_type == "BasicScheduler":
            inputs["steps"] = int(os.getenv("COMFYUI_STEPS", str(inputs.get("steps", 4))))
            inputs["scheduler"] = os.getenv("COMFYUI_SCHEDULER", inputs.get("scheduler", "simple"))
            inputs["denoise"] = float(os.getenv("COMFYUI_DENOISE", str(inputs.get("denoise", 1.0))))
        elif class_type == "KSamplerSelect":
            inputs["sampler_name"] = os.getenv("COMFYUI_SAMPLER", inputs.get("sampler_name", "euler"))
        elif class_type == "RandomNoise":
            inputs["noise_seed"] = int(os.getenv("COMFYUI_SEED", str(random.randint(1, 2**31 - 1))))
        elif class_type == "VAEDecodeTiled":
            inputs["tile_size"] = int(os.getenv("COMFYUI_VAE_TILE_SIZE", str(inputs.get("tile_size", 768))))
            inputs["overlap"] = int(os.getenv("COMFYUI_VAE_TILE_OVERLAP", str(inputs.get("overlap", 96))))
        elif class_type == "ImageScale":
            inputs["width"] = int(os.getenv("COMFYUI_WIDTH", str(inputs.get("width", 2688))))
            inputs["height"] = int(os.getenv("COMFYUI_HEIGHT", str(inputs.get("height", 2688))))
            inputs["upscale_method"] = os.getenv("COMFYUI_IMAGE_SCALE_METHOD", inputs.get("upscale_method", "lanczos"))
            inputs["crop"] = os.getenv("COMFYUI_IMAGE_SCALE_CROP", inputs.get("crop", "disabled"))
        elif class_type == "SaveImage":
            prefix = os.getenv("COMFYUI_OUTPUT_PREFIX", "hackster_niko")
            inputs["filename_prefix"] = f"{prefix}/{output_path.stem}"
        elif class_type == "LoadImage" and reference_image_name:
            inputs["image"] = reference_image_name

    if not positive_replaced:
        raise ValueError("Could not find a CLIPTextEncode node for the positive prompt in the ComfyUI workflow.")

    return workflow


def upload_reference_image_if_needed(base_url: str, workflow: dict[str, Any]) -> str | None:
    """Upload the configured reference image when the workflow contains a LoadImage node."""
    if not any(isinstance(node, dict) and node.get("class_type") == "LoadImage" for node in workflow.values()):
        return None
    existing_name = os.getenv("COMFYUI_REFERENCE_IMAGE_NAME")
    if existing_name:
        return existing_name
    reference_path_env = os.getenv("COMFYUI_REFERENCE_IMAGE")
    if not reference_path_env:
        raise ValueError("COMFYUI_REFERENCE_IMAGE is required for workflows with a LoadImage node.")
    reference_path = Path(reference_path_env).expanduser()
    if not reference_path.exists():
        raise FileNotFoundError(f"COMFYUI_REFERENCE_IMAGE not found: {reference_path}")
    return upload_image(base_url, reference_path)


def upload_image(base_url: str, image_path: Path) -> str:
    """Upload an input image to ComfyUI and return the LoadImage filename."""
    boundary = f"----hackster-niko-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    file_bytes = image_path.read_bytes()
    parts = [
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        + file_bytes
        + b"\r\n",
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="type"\r\n\r\n'
            "input\r\n"
        ).encode("utf-8"),
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
            "true\r\n"
        ).encode("utf-8"),
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    payload = b"".join(parts)
    request = urllib.request.Request(f"{base_url}/upload/image", data=payload, method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    username = os.getenv("COMFYUI_USERNAME")
    password = os.getenv("COMFYUI_PASSWORD")
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    return str(data.get("name") or image_path.name)


def submit_prompt(base_url: str, workflow: dict[str, Any]) -> str:
    payload = json.dumps({"prompt": workflow, "client_id": str(uuid.uuid4())}).encode("utf-8")
    response = request_json(f"{base_url}/prompt", method="POST", payload=payload)
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI /prompt did not return prompt_id: {response}")
    return str(prompt_id)


def wait_for_image(base_url: str, prompt_id: str, timeout_seconds: int = 600) -> bytes:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        history = request_json(f"{base_url}/history/{urllib.parse.quote(prompt_id)}")
        entry = history.get(prompt_id)
        if entry:
            error = comfyui_history_error(entry)
            if error:
                raise RuntimeError(f"ComfyUI prompt {prompt_id} failed: {error}")
            outputs = entry.get("outputs", {})
            image_info = first_image_info(outputs)
            if image_info:
                return download_image(base_url, image_info)
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}.")


def comfyui_history_error(entry: dict[str, Any]) -> str:
    """Extract the concise execution error from a ComfyUI history entry."""
    status = entry.get("status")
    if not isinstance(status, dict):
        return ""
    if status.get("status_str") != "error":
        return ""

    messages = status.get("messages")
    if not isinstance(messages, list):
        return "ComfyUI execution failed."
    for message in reversed(messages):
        if not isinstance(message, list) or len(message) < 2:
            continue
        event, payload = message[0], message[1]
        if event != "execution_error" or not isinstance(payload, dict):
            continue
        node_type = payload.get("node_type") or payload.get("node_id") or "unknown node"
        exception_type = payload.get("exception_type") or "Error"
        exception_message = str(payload.get("exception_message") or "").strip()
        if exception_message:
            return f"{node_type} {exception_type}: {exception_message}"
        return f"{node_type} {exception_type}"
    return "ComfyUI execution failed."


def first_image_info(outputs: dict[str, Any]) -> dict[str, Any] | None:
    for output in outputs.values():
        images = output.get("images") if isinstance(output, dict) else None
        if images:
            return images[0]
    return None


def download_image(base_url: str, image_info: dict[str, Any]) -> bytes:
    query = urllib.parse.urlencode(
        {
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        }
    )
    return request_bytes(f"{base_url}/view?{query}")


def request_json(url: str, method: str = "GET", payload: bytes | None = None) -> dict[str, Any]:
    data = request_bytes(url, method=method, payload=payload)
    return json.loads(data.decode("utf-8"))


def request_bytes(url: str, method: str = "GET", payload: bytes | None = None) -> bytes:
    request = urllib.request.Request(url, data=payload, method=method)
    request.add_header("Content-Type", "application/json")
    username = os.getenv("COMFYUI_USERNAME")
    password = os.getenv("COMFYUI_PASSWORD")
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ComfyUI request failed for {url}: {exc}") from exc


def default_flux_workflow() -> dict[str, Any]:
    tiled_decode = os.getenv("COMFYUI_TILED_DECODE", "true").lower() not in {"0", "false", "no"}
    decode_node = {
        "class_type": "VAEDecodeTiled",
        "inputs": {
            "samples": ["8", 0],
            "vae": ["4", 0],
            "tile_size": int(os.getenv("COMFYUI_VAE_TILE_SIZE", "768")),
            "overlap": int(os.getenv("COMFYUI_VAE_TILE_OVERLAP", "96")),
            "temporal_size": 64,
            "temporal_overlap": 8,
        },
        "_meta": {"title": "VAE Decode Tiled"},
    }
    if not tiled_decode:
        decode_node = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["8", 0], "vae": ["4", 0]},
            "_meta": {"title": "VAE Decode"},
        }

    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": os.getenv("COMFYUI_UNET", "flux1-schnell.safetensors"),
                "weight_dtype": os.getenv("COMFYUI_UNET_DTYPE", "fp8_e4m3fn"),
            },
            "_meta": {"title": "Load FLUX UNET"},
        },
        "2": {
            "class_type": "ModelSamplingFlux",
            "inputs": {
                "model": ["1", 0],
                "max_shift": 1.15,
                "base_shift": 0.5,
                "width": int(os.getenv("COMFYUI_GENERATION_WIDTH", "1344")),
                "height": int(os.getenv("COMFYUI_GENERATION_HEIGHT", "1344")),
            },
            "_meta": {"title": "ModelSamplingFlux"},
        },
        "3": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": os.getenv("COMFYUI_CLIP_1", "t5xxl_fp16.safetensors"),
                "clip_name2": os.getenv("COMFYUI_CLIP_2", "clip_l.safetensors"),
                "type": os.getenv("COMFYUI_CLIP_TYPE", "flux"),
            },
            "_meta": {"title": "Load Dual CLIP"},
        },
        "4": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": os.getenv("COMFYUI_VAE", "ae.safetensors")},
            "_meta": {"title": "Load VAE"},
        },
        "5": {
            "class_type": "CLIPTextEncodeFlux",
            "inputs": {"clip": ["3", 0], "clip_l": "", "t5xxl": "", "guidance": 3.5},
            "_meta": {"title": "Positive Prompt"},
        },
        "6": {
            "class_type": "CLIPTextEncodeFlux",
            "inputs": {"clip": ["3", 0], "clip_l": "", "t5xxl": "", "guidance": 3.5},
            "_meta": {"title": "Negative Prompt"},
        },
        "7": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": int(os.getenv("COMFYUI_GENERATION_WIDTH", "1344")),
                "height": int(os.getenv("COMFYUI_GENERATION_HEIGHT", "1344")),
                "batch_size": 1,
            },
            "_meta": {"title": "Empty Latent"},
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1,
                "steps": 20,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["2", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["7", 0],
            },
            "_meta": {"title": "KSampler"},
        },
        "9": decode_node,
        "10": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["9", 0],
                "upscale_method": os.getenv("COMFYUI_IMAGE_SCALE_METHOD", "lanczos"),
                "width": int(os.getenv("COMFYUI_WIDTH", "2688")),
                "height": int(os.getenv("COMFYUI_HEIGHT", "2688")),
                "crop": "disabled",
            },
            "_meta": {"title": "Scale to Print Pixels"},
        },
        "11": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "hackster_niko", "images": ["10", 0]},
            "_meta": {"title": "Save Image"},
        },
    }


def default_flux_pulid_workflow() -> dict[str, Any]:
    """FLUX.1-dev workflow with PuLID identity conditioning from a reference image."""
    workflow = default_flux_workflow()
    workflow["2"]["inputs"]["model"] = ["12", 0]
    workflow["12"] = {
        "class_type": "ApplyPulidFlux",
        "inputs": {
            "model": ["1", 0],
            "pulid_flux": ["13", 0],
            "eva_clip": ["14", 0],
            "face_analysis": ["15", 0],
            "image": ["16", 0],
            "weight": float(os.getenv("COMFYUI_PULID_WEIGHT", "0.85")),
            "start_at": float(os.getenv("COMFYUI_PULID_START_AT", "0.0")),
            "end_at": float(os.getenv("COMFYUI_PULID_END_AT", "1.0")),
        },
        "_meta": {"title": "Apply PuLID Flux"},
    }
    workflow["13"] = {
        "class_type": "PulidFluxModelLoader",
        "inputs": {"pulid_file": os.getenv("COMFYUI_PULID_MODEL", "pulid_flux_v0.9.0.safetensors")},
        "_meta": {"title": "Load PuLID Flux Model"},
    }
    workflow["14"] = {
        "class_type": "PulidFluxEvaClipLoader",
        "inputs": {},
        "_meta": {"title": "Load EVA CLIP"},
    }
    workflow["15"] = {
        "class_type": "PulidFluxInsightFaceLoader",
        "inputs": {"provider": os.getenv("COMFYUI_PULID_INSIGHTFACE_PROVIDER", "CPU")},
        "_meta": {"title": "Load InsightFace"},
    }
    workflow["16"] = {
        "class_type": "LoadImage",
        "inputs": {"image": "niko_reference.png"},
        "_meta": {"title": "Niko Reference Image"},
    }
    return workflow


def default_sdxl_workflow() -> dict[str, Any]:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": os.getenv("COMFYUI_CHECKPOINT", "sd_xl_base_1.0.safetensors")},
            "_meta": {"title": "Load Checkpoint"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": ""},
            "_meta": {"title": "Positive Prompt"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": ""},
            "_meta": {"title": "Negative Prompt"},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
            "_meta": {"title": "Empty Latent"},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1,
                "steps": 30,
                "cfg": 7,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
            "_meta": {"title": "Sampler"},
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            "_meta": {"title": "VAE Decode"},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "hackster_niko", "images": ["6", 0]},
            "_meta": {"title": "Save Image"},
        },
    }
