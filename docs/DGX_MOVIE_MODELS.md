# DGX Movie Models

DGX host alias:

```bash
ssh sync-spark-d1a9_local
```

ComfyUI endpoint:

```text
http://192.168.68.136:8188
```

## Installed For Keyframes

These were already installed before the movie model pass:

- `flux1-dev.safetensors`
- `flux1-schnell.safetensors`
- `clip_l.safetensors`
- `t5xxl_fp16.safetensors`
- `ae.safetensors`

## Installed For Video

ComfyUI model root:

```text
/home/pizzacat/ai/comfyui/ComfyUI/models
```

Wan 2.2 files installed:

- `diffusion_models/wan2.2_ti2v_5B_fp16.safetensors`
- `diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors`
- `diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors`
- `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`
- `vae/wan2.2_vae.safetensors`
- `vae/wan_2.1_vae.safetensors`
- `loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors`
- `loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors`

## Installed For Audio And Lip-Sync

Local model root:

```text
/home/pizzacat/ai/movie_models
```

Snapshots installed:

- `chatterbox-turbo` from `ResembleAI/chatterbox-turbo`
- `chatterbox-multilingual` from `ResembleAI/chatterbox`
- `latentsync-1.6` from `ByteDance/LatentSync-1.6`
- `ace-step-v1-3.5B` from `ACE-Step/ACE-Step-v1-3.5B`
- `audioldm2` from `cvssp/audioldm2`
- `qwen3.6-35b-a3b` from `Qwen/Qwen3.6-35B-A3B`

Stable Audio Open was not installed because `stabilityai/stable-audio-open-1.0` is gated for the current Hugging Face token. AudioLDM2 is the default non-gated SFX/ambience fallback.

## Installer

The repeatable installer lives in the repo:

```text
tools/dgx/install_movie_models.py
```

The copy used on the DGX is:

```text
/home/pizzacat/ai/installers/install_movie_models.py
```

Rerun:

```bash
ssh sync-spark-d1a9_local 'python3 /home/pizzacat/ai/installers/install_movie_models.py'
```

The local LLM install was completed with `--with-llm`; rerunning that command is safe and idempotent.

## Verification

```bash
ssh sync-spark-d1a9_local 'curl -sS http://127.0.0.1:8188/models/diffusion_models'
ssh sync-spark-d1a9_local 'curl -sS http://127.0.0.1:8188/models/text_encoders'
ssh sync-spark-d1a9_local 'curl -sS http://127.0.0.1:8188/models/vae'
ssh sync-spark-d1a9_local 'curl -sS http://127.0.0.1:8188/models/loras'
```
