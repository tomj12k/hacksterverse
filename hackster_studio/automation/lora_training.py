"""ComfyUI-native FLUX LoRA training for character reference sets.

The DGX ComfyUI exposes the built-in training nodes (MakeTrainingDataset,
TrainLoraNode, SaveLoRA), so training is driven the same way as image
generation: upload the selected dataset images, POST a training graph, and poll
until it finishes. Invoked as the configured HACKSTER_DGX_LORA_TRAINER_CMD via
``python -m hackster_studio.automation.lora_training`` (env vars provided by the
launcher / _start_lora_training).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .comfyui_engine import comfyui_history_error, request_json, submit_prompt, upload_image
from ..config import PROJECT_ROOT


def _base_url() -> str:
    return (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")


def free_comfyui_memory(base_url: str) -> None:
    """Unload models + free cached memory before training.

    On the unified-memory DGX (GB10), VRAM and system RAM are one pool. ComfyUI
    holds ~88GB of loaded models/working set from image generation, leaving too
    little for a FLUX training step -> kernel OOM-kill. Clearing first lets the
    training graph reload into a near-empty pool. Best-effort.
    """
    import urllib.request

    payload = json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8")
    request = urllib.request.Request(f"{base_url}/free", data=payload, method="POST")
    request.add_header("Content-Type", "application/json")
    username = os.getenv("COMFYUI_USERNAME")
    password = os.getenv("COMFYUI_PASSWORD")
    if username and password:
        import base64

        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        print("[lora] requested ComfyUI /free (unload models, free memory)", flush=True)
    except Exception as exc:  # noqa: BLE001 - freeing is best-effort
        print(f"[lora] /free request failed (continuing): {exc}", flush=True)


def build_training_workflow(
    image_filenames: list[str],
    *,
    steps: int,
    rank: int,
    learning_rate: float,
    seed: int,
    output_prefix: str,
    captions: list[str] | None = None,
    offloading: bool = True,
    training_dtype: str = "bf16",
    quantized_backward: bool = False,
) -> dict[str, Any]:
    """Build a ComfyUI FLUX LoRA training graph for the uploaded images."""
    workflow: dict[str, Any] = {
        "model": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": os.getenv("COMFYUI_UNET", "flux1-dev.safetensors"),
                "weight_dtype": os.getenv("COMFYUI_UNET_DTYPE", "default"),
            },
        },
        "clip": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": os.getenv("COMFYUI_CLIP_1", "clip_l.safetensors"),
                "clip_name2": os.getenv("COMFYUI_CLIP_2", "t5xxl_fp16.safetensors"),
                "type": os.getenv("COMFYUI_CLIP_TYPE", "flux"),
            },
        },
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": os.getenv("COMFYUI_VAE", "ae.safetensors")}},
    }

    # One LoadImage per uploaded file, batched together into a single IMAGE.
    image_ids: list[str] = []
    for index, filename in enumerate(image_filenames):
        node_id = f"img{index}"
        workflow[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        image_ids.append(node_id)

    if len(image_ids) == 1:
        images_ref: list[Any] = [image_ids[0], 0]
    else:
        prev = image_ids[0]
        for index in range(1, len(image_ids)):
            batch_id = f"batch{index}"
            workflow[batch_id] = {
                "class_type": "ImageBatch",
                "inputs": {"image1": [prev, 0], "image2": [image_ids[index], 0]},
            }
            prev = batch_id
        images_ref = [prev, 0]

    dataset_inputs: dict[str, Any] = {"images": images_ref, "vae": ["vae", 0], "clip": ["clip", 0]}
    if captions:
        # A single caption is repeated for all images by MakeTrainingDataset.
        workflow["caption"] = {"class_type": "String", "inputs": {"value": captions[0]}}
        dataset_inputs["texts"] = ["caption", 0]
    workflow["dataset"] = {"class_type": "MakeTrainingDataset", "inputs": dataset_inputs}

    workflow["train"] = {
        "class_type": "TrainLoraNode",
        "inputs": {
            "model": ["model", 0],
            "latents": ["dataset", 0],
            "positive": ["dataset", 1],
            "batch_size": 1,
            "grad_accumulation_steps": 1,
            "steps": int(steps),
            "learning_rate": float(learning_rate),
            "rank": int(rank),
            "optimizer": "AdamW",
            "loss_function": "MSE",
            "seed": int(seed),
            "training_dtype": training_dtype,
            "lora_dtype": "bf16",
            "quantized_backward": bool(quantized_backward),
            "algorithm": "LoRA",
            "gradient_checkpointing": True,
            "checkpoint_depth": 1,
            "offloading": bool(offloading),
            "existing_lora": "[None]",
            "bucket_mode": False,
            "bypass_mode": False,
        },
    }
    workflow["save"] = {
        "class_type": "SaveLoRA",
        "inputs": {"lora": ["train", 0], "prefix": output_prefix, "steps": ["train", 2]},
    }
    return workflow


def _prepare_training_image(path: Path, max_dim: int, tmp_dir: Path) -> Path:
    """Downscale to <= max_dim and flatten transparency onto white.

    FLUX training cost scales with latent area, so native 1536px cutouts blow
    up memory; 768px is the standard training size. Transparent character
    cutouts are composited on white so the VAE encodes a clean image.
    """
    from PIL import Image

    image = Image.open(path).convert("RGBA")
    width, height = image.size
    scale = min(1.0, max_dim / max(width, height))
    if scale < 1.0:
        image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    flattened = Image.alpha_composite(background, image).convert("RGB")
    out_path = tmp_dir / f"{path.stem}_train.png"
    flattened.save(out_path)
    return out_path


def _dataset_images_and_captions(manifest_path: Path) -> tuple[list[Path], list[str]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    images: list[Path] = []
    captions: list[str] = []
    for item in data.get("images", []):
        rel = str(item.get("path") or "")
        if not rel:
            continue
        path = (PROJECT_ROOT / rel) if not Path(rel).is_absolute() else Path(rel)
        if path.exists():
            images.append(path)
            captions.append(str(item.get("caption") or ""))
    return images, captions


def wait_for_training(base_url: str, prompt_id: str, timeout_seconds: int) -> None:
    """Block until a training prompt finishes (no image output to fetch)."""
    deadline = time.time() + timeout_seconds
    import urllib.parse

    while time.time() < deadline:
        history = request_json(f"{base_url}/history/{urllib.parse.quote(prompt_id)}")
        entry = history.get(prompt_id)
        if entry:
            error = comfyui_history_error(entry)
            if error:
                raise RuntimeError(f"ComfyUI training prompt {prompt_id} failed: {error}")
            status = entry.get("status", {})
            if status.get("completed") or status.get("status_str") == "success":
                return
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for ComfyUI training prompt {prompt_id}.")


def train_lora_comfyui(
    manifest_path: Path,
    *,
    slug: str,
    output_prefix: str,
    steps: int,
    rank: int,
    learning_rate: float,
    seed: int = 0,
    use_captions: bool = True,
    offloading: bool = True,
    training_dtype: str = "bf16",
    quantized_backward: bool = False,
    train_resolution: int = 768,
    timeout_seconds: int = 7200,
) -> str:
    import tempfile

    base_url = _base_url()
    images, captions = _dataset_images_and_captions(manifest_path)
    if not images:
        raise RuntimeError(f"No dataset images found via {manifest_path}")
    # Free held models first so training has the full unified-memory pool.
    free_comfyui_memory(base_url)
    tmp_dir = Path(tempfile.mkdtemp(prefix="hackster_lora_"))
    prepared = [_prepare_training_image(path, train_resolution, tmp_dir) for path in images]
    print(f"[lora] uploading {len(prepared)} images (<= {train_resolution}px) to ComfyUI {base_url}", flush=True)
    uploaded = [upload_image(base_url, path) for path in prepared]
    trigger_caption = captions[0] if (use_captions and captions and captions[0]) else ""
    workflow = build_training_workflow(
        uploaded,
        steps=steps,
        rank=rank,
        learning_rate=learning_rate,
        seed=seed,
        output_prefix=output_prefix,
        captions=[trigger_caption] if trigger_caption else None,
        offloading=offloading,
        training_dtype=training_dtype,
        quantized_backward=quantized_backward,
    )
    print(f"[lora] submitting training graph: steps={steps} rank={rank} lr={learning_rate} prefix={output_prefix}", flush=True)
    prompt_id = submit_prompt(base_url, workflow)
    print(f"[lora] training prompt_id={prompt_id}; polling (timeout {timeout_seconds}s)", flush=True)
    wait_for_training(base_url, prompt_id, timeout_seconds)
    print(f"[lora] training complete; LoRA saved under ComfyUI loras/ as {output_prefix}*.safetensors", flush=True)
    return prompt_id


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    manifest = os.getenv("HACKSTER_LORA_DATASET_MANIFEST", "")
    slug = os.getenv("HACKSTER_CHARACTER_SLUG", "character")
    if not manifest or not Path(manifest).exists():
        print(f"[lora] dataset manifest not found: {manifest!r}", file=sys.stderr)
        return 2
    prefix = os.getenv("HACKSTER_LORA_OUTPUT_PREFIX", f"hackster/{slug}")
    try:
        train_lora_comfyui(
            Path(manifest),
            slug=slug,
            output_prefix=prefix,
            steps=int(os.getenv("HACKSTER_LORA_STEPS", "1000")),
            rank=int(os.getenv("HACKSTER_LORA_RANK", "16")),
            learning_rate=float(os.getenv("HACKSTER_LORA_LEARNING_RATE", "0.0005")),
            seed=int(os.getenv("HACKSTER_LORA_SEED", "0")),
            offloading=os.getenv("HACKSTER_LORA_OFFLOADING", "1").strip().lower() not in ("", "0", "false", "no"),
            train_resolution=int(os.getenv("HACKSTER_LORA_TRAIN_RESOLUTION", "768")),
            timeout_seconds=int(os.getenv("HACKSTER_LORA_TIMEOUT", "7200")),
        )
    except Exception as exc:  # noqa: BLE001 - surface any backend failure to the log
        print(f"[lora] training failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
