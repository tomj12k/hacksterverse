# Niko Consistency Pilot QA

## Current Status

The manuscript/dialogue layer is fixed in the generated page YAML and production PDF text. The image-generation prompts are now visual-only prompts and no longer include manuscript dialogue or Markdown headings that caused fake text/page layouts.

## Pilot Results

- `page_004_niko_lock.png`: failed. Rendered fake page text and split-page layout.
- `page_004_niko_lock_v2.png`: failed. Removed fake text, but retained strong screen-door/grid texture.
- `page_004_niko_lock_v3.png`: failed. Non-tiled 2688 decode still retained grid texture and duplicated Niko-like robot forms.
- `page_004_native1344.png`: useful diagnostic. Cleanest scene, but not final print size.
- `page_004_native1344_v4.png`: closer, but still too soft and includes a tail-like curve near Niko.
- `page_004_native1344_v4_2x_lanczos.png`: production-size candidate, but not approved due softness and tail-like curve.

## Production Decision

Do not run the full 32-page production image pass until the Niko reference/consistency workflow is stronger. Prompt-only FLUX generation is not enough for 100% character consistency.

## Next Required Fix

Add a reference-locked character workflow for Niko, ideally using ComfyUI reference-image/Kontext/IPAdapter-style conditioning or a LoRA/reference model. Once Niko passes a pilot page with no tail, no mouth, no duplicate robot, and no grid texture, regenerate the full book images.
