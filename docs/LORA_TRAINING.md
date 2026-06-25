# Character LoRA Training (ComfyUI-native)

The character bench's **Process Selected Set Now** button can submit a FLUX LoRA
training job for the selected examples. Training is driven through the DGX
ComfyUI's built-in training nodes (`MakeTrainingDataset` → `TrainLoraNode` →
`SaveLoRA`) over HTTP — the same path as image generation.

Implementation: `hackster_studio/automation/lora_training.py`
(entry point `python -m hackster_studio.automation.lora_training`).

## Status: integration works, full training does NOT fit on the current DGX

The graph is valid and submits cleanly every time. A real training run, however,
**runs out of memory** on the current DGX (NVIDIA **GB10**, 121 GB **unified**
memory — GPU and system RAM are one pool). Training is therefore **opt-in and
disabled by default**: `HACKSTER_DGX_LORA_TRAINER_CMD` is unset, so the button
safely dry-runs (see `scripts/train_lora_dgx.sh`).

### Root causes found (in order)

1. **Pinned memory reserves 90% of RAM.** ComfyUI logs `Enabled pinned memory
   112148.0` — `MAX_PINNED_MEMORY = ram * 0.90` ≈ 109 GB of 121 GB, page-locked.
   With ~50 MB free, any training allocation triggers a **kernel OOM-kill** that
   takes the whole ComfyUI server down (no Python traceback; see
   `journalctl -k | grep "Out of memory: Killed"`, `task_memcg=…/comfyui.service`).
   - Fix: launch ComfyUI with **`--disable-pinned-memory`**. This stops the hard
     crash — the server then survives and raises a *graceful* torch OOM instead.
     Trade-off: it can slow image generation (offload via unpinned RAM), so it is
     **not** applied by default.

2. **`comfy-aimdo` allowed-memory budget.** Even with pinning disabled and images
   downscaled to 768², training fails with
   `torch.OutOfMemoryError: Allocation on device 0 would exceed allowed memory`.
   "allowed memory" is the `comfy-aimdo` DynamicVRAM manager's budget — a custom
   DGX component capping allocations below the full pool. FLUX 12B training
   exceeds it, and one run still reached a kernel OOM. Resolving this needs
   `comfy-aimdo` configuration on the box (no client-side knob).

## To enable real training (DGX-side work required)

1. Add `--disable-pinned-memory` to `~/ai/comfyui/start_comfyui.sh` and
   `systemctl --user restart comfyui.service` (a backup `.bak` is created by the
   edit). Accept the image-gen trade-off, or benchmark it first.
2. Raise / tune the `comfy-aimdo` allowed-memory budget so a 12B-model training
   allocation fits, OR reduce training memory:
   - text encoder: use `t5xxl_fp8` instead of `t5xxl_fp16` (`COMFYUI_CLIP_2`),
   - train at 512² (`HACKSTER_LORA_TRAIN_RESOLUTION=512`),
   - smaller rank, fewer images per dataset.
3. Set the trainer command and re-test with `steps=1` first:
   ```
   HACKSTER_DGX_LORA_TRAINER_CMD=.venv/bin/python -m hackster_studio.automation.lora_training
   ```

## Trainer env vars

| Var | Default | Notes |
|-----|---------|-------|
| `HACKSTER_DGX_LORA_TRAINER_CMD` | (unset) | Set to enable real training |
| `HACKSTER_LORA_STEPS` | 1000 | training steps |
| `HACKSTER_LORA_RANK` | 16 | LoRA rank |
| `HACKSTER_LORA_LEARNING_RATE` | 0.0005 | |
| `HACKSTER_LORA_TRAIN_RESOLUTION` | 768 | images downscaled to this; lower = less memory |
| `HACKSTER_LORA_OFFLOADING` | 1 | offload weights to CPU during training |
| `HACKSTER_LORA_MIN_IMAGES` | 20 | auto-submit threshold from the bench |
| `HACKSTER_LORA_OUTPUT_PREFIX` | `hackster/<slug>` | SaveLoRA prefix in ComfyUI `loras/` |

The trainer downscales + flattens the transparent cutouts onto white, uploads
them, calls ComfyUI `/free`, then submits the training graph and polls. Output
LoRA lands in ComfyUI's `loras/` and is usable by `LoraLoader` immediately.
