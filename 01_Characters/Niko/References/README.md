# Niko Reference Assets

These files track the current preferred visual direction for Hackster Niko.

## Primary Reference

- `niko_realistic_reference_page004_upper_body.png`

Use this as the first identity/style reference for FLUX reference-adapter tests or Niko LoRA dataset planning. It preserves the liked dimensional storybook look without the lower-body tail-like artifact from the original pilot.

## Supporting References

- `niko_realistic_reference_page004_full.png` - full scene reference for lighting, mood, and material softness.
- `niko_realistic_reference_page004_portrait.png` - full-body comparison crop only; do not use as the primary identity reference because it includes an old tail-like artifact.
- `niko_realistic_reference_page004_portrait_no_tail.png` - experimental inpainted cleanup; useful for comparison, not a master model sheet.

## TODO

- TODO: Generate a clean front, side, three-quarter, and back turnaround in this realistic storybook style.
- TODO: Create 10-20 approved Niko references for LoRA training.
- TODO: Keep every approved reference free of mouth marks, tails, dangling cords, labels, decals, and antenna drift.
- TODO: Save approved references with names like `HN_Character_Niko_Reference_Front_v001.png`.
