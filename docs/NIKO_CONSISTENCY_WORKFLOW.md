# Niko Consistency Workflow

## Problem

Prompt-only FLUX generation changes Hackster Niko from page to page. The head shape, antenna, body proportions, backpack, limbs, and tail-like artifacts drift because the model redraws the main character independently for every page.

## Current Art Direction Decision

The simple deterministic overlay fixed consistency, but it is too flat/cartoonish for the final book. The preferred Niko is the more dimensional FLUX-rendered storybook robot from the page-4 pilot.

Approved working references:

- `01_Characters/Niko/References/niko_realistic_reference_page004_upper_body.png` - primary identity/style reference.
- `01_Characters/Niko/References/niko_realistic_reference_page004_full.png` - lighting and scene reference.
- `01_Characters/Niko/References/niko_realistic_reference_page004_portrait.png` - comparison only; do not use as the main reference because it contains a tail-like artifact.

## Current Production Rule

Do not run the full 32-page production image pass until Niko has a realistic consistency mechanism:

1. Preferred: install/use a FLUX reference adapter such as PuLID for FLUX or FLUX Redux with the approved Niko reference.
2. Best long-term: train a dedicated Niko LoRA from 10-20 approved Niko reference images with a unique trigger token such as `HN01Niko`.
3. Engineering fallback only: simple deterministic overlay.

The fallback overlay can still be useful for testing page layout and text placement, but it should not be treated as final book art unless explicitly approved.

## Engineering Fallback

Niko must not be generated as part of the page background.

Instead:

1. Generate backgrounds and non-Niko characters with ComfyUI.
2. Leave an empty reserved area for Niko.
3. Composite a deterministic locked Niko transparent PNG pose onto the page.
4. Use the composited page for PDF/Affinity output.

This guarantees geometry, but not the desired final style:

- same antenna geometry
- same head shape
- same body proportions
- same Core Crystal
- same no-mouth face
- no tail
- no animal anatomy

## Files

- Pose assets: `01_Characters/Niko/Poses/niko_*.png`
- Realistic Niko references: `01_Characters/Niko/References/niko_realistic_reference_page004_*.png`
- Page placement manifest: `books/book01_password_dragon/reports/niko_character_lock_manifest.md`
- Background prompts: `books/book01_password_dragon/prompts/page_*.md`
- Locked final composites: `books/book01_password_dragon/illustrations_locked/page_*.png`

## Commands

Run normal realistic prompt generation:

```bash
PYTHONPATH=. .venv/bin/python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --no-images --no-pdf --no-production-pdf --no-idml --force
```

Render locked Niko pose assets for engineering fallback:

```bash
PYTHONPATH=. .venv/bin/python -m hackster_studio.cli build-niko-lock --force
```

Regenerate background-only prompts for engineering fallback:

```bash
HACKSTER_NIKO_LAYER_MODE=locked_overlay PYTHONPATH=. .venv/bin/python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --no-images --no-pdf --no-production-pdf --no-idml --force
```

Composite locked Niko onto existing generated backgrounds for engineering fallback:

```bash
HACKSTER_NIKO_LAYER_MODE=locked_overlay PYTHONPATH=. .venv/bin/python -m hackster_studio.cli compose-niko-lock books/book01_password_dragon/book.yaml --force
```

## Future Fully Generative Option

For Niko to be drawn naturally by FLUX inside every scene, train a dedicated Niko LoRA or install a FLUX identity/reference adapter.

Preferred options:

- Train a Niko LoRA from 10-20 approved Niko reference images and use a unique trigger token such as `HN01Niko`.
- Install/use a FLUX-compatible identity/reference workflow such as PuLID for FLUX or FLUX Redux if available.

Current DGX finding:

- `LoraLoader` and `TrainLoraNode` are available.
- PuLID FLUX nodes were not present in the current ComfyUI node inventory.
- No Niko LoRA is currently installed.

Until a LoRA or FLUX reference adapter is working, the full book should stay blocked at the production gate rather than accepting a character style we do not like.
