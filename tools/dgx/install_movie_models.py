"""Install Hackster Niko movie models on the DGX Spark.

Run this on the DGX. It is idempotent and uses Hugging Face Hub downloads.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download


WAN_REPO = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"

WAN_FILES = {
    "diffusion_models": [
        "wan2.2_ti2v_5B_fp16.safetensors",
        "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    ],
    "text_encoders": [
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    ],
    "vae": [
        "wan2.2_vae.safetensors",
        "wan_2.1_vae.safetensors",
    ],
    "loras": [
        "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
        "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    ],
}

SNAPSHOT_REPOS = [
    ("ResembleAI/chatterbox-turbo", "chatterbox-turbo"),
    ("ResembleAI/chatterbox", "chatterbox-multilingual"),
    ("ByteDance/LatentSync-1.6", "latentsync-1.6"),
    ("ACE-Step/ACE-Step-v1-3.5B", "ace-step-v1-3.5B"),
    ("cvssp/audioldm2", "audioldm2"),
]

SAFETENSOR_PATTERNS = [
    "*.json",
    "*.md",
    "*.txt",
    "*.model",
    "*.safetensors",
    "tokenizer/*",
    "tokenizer_2/*",
    "feature_extractor/*",
    "scheduler/*",
]

OPTIONAL_SNAPSHOT_REPOS = [
    ("Qwen/Qwen3.6-35B-A3B", "qwen3.6-35b-a3b"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", default="/home/pizzacat/ai/movie_models")
    parser.add_argument("--comfy-models-root", default="/home/pizzacat/ai/comfyui/ComfyUI/models")
    parser.add_argument("--with-llm", action="store_true", help="Also install Qwen3.6-35B-A3B for local script planning.")
    args = parser.parse_args()

    model_root = Path(args.model_root).expanduser()
    comfy_root = Path(args.comfy_models_root).expanduser()
    cache_root = model_root / "_hf_cache"
    model_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    print(f"Model root: {model_root}")
    print(f"ComfyUI model root: {comfy_root}")

    install_wan_files(model_root, comfy_root)
    install_snapshots(model_root, SNAPSHOT_REPOS)
    if args.with_llm:
        install_snapshots(model_root, OPTIONAL_SNAPSHOT_REPOS)

    write_manifest(model_root, include_llm=args.with_llm)
    print("\nDone. Restart ComfyUI if it does not refresh the Wan model lists automatically.")


def install_wan_files(model_root: Path, comfy_root: Path) -> None:
    repo_cache = model_root / "wan_2.2_comfyui_repackaged"
    for folder, filenames in WAN_FILES.items():
        for filename in filenames:
            repo_filename = f"split_files/{folder}/{filename}"
            print(f"\n[Wan] {filename}")
            source = Path(
                hf_hub_download(
                    repo_id=WAN_REPO,
                    filename=repo_filename,
                    local_dir=repo_cache,
                    local_dir_use_symlinks=False,
                )
            )
            destination = comfy_root / folder / filename
            install_file(source, destination)


def install_snapshots(model_root: Path, repos: list[tuple[str, str]]) -> None:
    for repo_id, local_name in repos:
        destination = model_root / local_name
        print(f"\n[Snapshot] {repo_id} -> {destination}")
        kwargs: dict[str, object] = {}
        if repo_id == "cvssp/audioldm2":
            kwargs["allow_patterns"] = SAFETENSOR_PATTERNS
            kwargs["ignore_patterns"] = ["*.bin"]
        snapshot_download(
            repo_id=repo_id,
            local_dir=destination,
            local_dir_use_symlinks=False,
            **kwargs,
        )


def install_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size == source.stat().st_size:
        print(f"  exists: {destination}")
        return
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    try:
        os.link(source, tmp)
    except OSError:
        shutil.copy2(source, tmp)
    tmp.replace(destination)
    print(f"  installed: {destination}")


def write_manifest(model_root: Path, *, include_llm: bool) -> None:
    lines = [
        "# Hackster Niko DGX Movie Models",
        "",
        "## ComfyUI Wan Files",
    ]
    for folder, filenames in WAN_FILES.items():
        lines.append("")
        lines.append(f"### {folder}")
        lines.extend(f"- {filename}" for filename in filenames)
    lines.append("")
    lines.append("## Local Model Snapshots")
    for repo_id, local_name in SNAPSHOT_REPOS:
        lines.append(f"- {repo_id}: {model_root / local_name}")
    if include_llm:
        for repo_id, local_name in OPTIONAL_SNAPSHOT_REPOS:
            lines.append(f"- {repo_id}: {model_root / local_name}")
    (model_root / "INSTALL_MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
