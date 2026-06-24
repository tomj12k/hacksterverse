# Niko Character Lock Manifest

Mode: realistic generated character

The simple deterministic overlay is disabled for production by default because it is too flat for the approved art direction.

Current production target:

- Use the realistic FLUX-rendered Niko as the visual target.
- Do not approve a full book run until the DGX has either a working FLUX reference adapter workflow or a trained Niko LoRA.
- To run the simple overlay only for engineering tests, set `HACKSTER_NIKO_LAYER_MODE=locked_overlay`.
