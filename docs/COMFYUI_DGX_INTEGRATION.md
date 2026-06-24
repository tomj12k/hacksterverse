# ComfyUI DGX Integration

Target DGX/LAN server:

```text
http://192.168.68.136:8188
```

Hackster Studio can call this ComfyUI server with:

```bash
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --generate-images --image-backend comfyui --build-pdf
```

## Hackster Studio Configuration

Copy `.env.example` to `.env` and set:

```text
HACKSTER_IMAGE_BACKEND=comfyui
COMFYUI_URL=http://192.168.68.136:8188
COMFYUI_WORKFLOW_KIND=flux
COMFYUI_UNET=flux1-schnell.safetensors
COMFYUI_CLIP_1=clip_l.safetensors
COMFYUI_CLIP_2=t5xxl_fp16.safetensors
COMFYUI_VAE=ae.safetensors
```

For full DGX model handoff, enable managed profiles:

```text
HACKSTER_DGX_MANAGE_SERVICES=1
HACKSTER_DGX_MODEL_CONFIG=configs/dgx_model_profiles.yaml
HACKSTER_DGX_PLANNER_PROFILE=qwen3_32b_awq
HACKSTER_DGX_IMAGE_PROFILE=flux_dev
```

Optional auth proxy settings:

```text
COMFYUI_USERNAME=
COMFYUI_PASSWORD=
```

Keep credentials in `.env`; do not hardcode or commit them.

## DGX Setup Notes

Preferred remote structure:

```text
~/ai/
~/ai/comfyui/
~/ai/comfyui/ComfyUI
~/ai/comfyui/venv
~/ai/models/checkpoints/
~/ai/models/vae/
~/ai/models/loras/
~/ai/models/controlnet/
~/ai/models/upscalers/
~/ai/workflows/
~/ai/outputs/
~/ai/logs/
```

Start command:

```bash
cd ~/ai/comfyui/ComfyUI
source ~/ai/comfyui/venv/bin/activate
python main.py --listen 0.0.0.0 --port 8188 --output-directory ~/ai/outputs
```

ComfyUI is intended for trusted LAN use only. Do not port-forward `8188` to the public internet. Use a VPN or SSH tunnel for remote access.

## API Checks

From the DGX:

```bash
curl http://127.0.0.1:8188/system_stats
```

From this Mac/workstation:

```bash
curl http://192.168.68.136:8188/system_stats
```

## Workflow Notes

Hackster Studio can use either:

- a built-in FLUX API workflow, controlled by `COMFYUI_UNET`, `COMFYUI_CLIP_1`, `COMFYUI_CLIP_2`, and `COMFYUI_VAE`
- a built-in SDXL/checkpoint workflow by setting `COMFYUI_WORKFLOW_KIND=sdxl`, controlled by `COMFYUI_CHECKPOINT`
- a custom exported ComfyUI API workflow via `COMFYUI_WORKFLOW_PATH`

For custom workflows, use ComfyUI's API workflow JSON format. The integration replaces the positive `CLIPTextEncode` text with each page prompt and sends the workflow to `/prompt`.

## Managed Model Profiles

Model profiles live in `configs/dgx_model_profiles.yaml`.

The pipeline uses role-based profiles:

- `planner.qwen3_32b_awq` starts `vllm-planner.service`, waits for `http://192.168.68.136:8000/v1/models`, and sets `DGX_LLM_MODEL=Qwen3-32B-AWQ`.
- `image.flux_dev` stops vLLM, starts `comfyui.service`, waits for `http://192.168.68.136:8188/system_stats`, and sets the FLUX-dev ComfyUI variables.
- `image.flux_schnell` is available for faster draft renders.
- `image.flux_pulid` is available for reference-driven character consistency workflows.

Add future planner, image, pose, text-art, or video models as new profiles. Prefer one systemd service per heavyweight exclusive model server, then list incompatible services in `stop_services`.

## Model Notes

Good starting families for children's book illustration:

- SDXL base or a local SDXL illustration checkpoint
- FLUX.1-schnell or FLUX.1-dev if licensing/access is available
- later LoRAs for Niko consistency and series style

Do not download gated or huge models until disk space, licensing, and tokens are confirmed.
