# Storybook Maker App

## Direction

The book pipeline should move from single baked page images to editable layered scenes.

Each page becomes a scene graph:

- background plates
- Niko character cutouts
- friend character cutouts
- props and interactable objects
- hidden objects
- lighting overlays
- camera/safe-area framing
- editable story text

This lets us arrange, pose, and reuse assets instead of rerolling an entire page when one detail is wrong.

## Asset Pipeline

Generate assets as separate transparent PNG layers:

1. Background only, no characters.
2. Character master cutouts on clean/chroma background.
3. Character expression and pose sheets.
4. Friend and creature cutouts.
5. Props and hidden objects.
6. Light/shadow overlays.
7. Camera framing metadata.

For Niko, the preferred visual target is:

- `01_Characters/Niko/References/niko_approved_pulid_style_page004_v001.png`

The simple vector Niko overlay remains an engineering fallback only.

## Rigging Model

Each character layer can have a 2D skeleton:

- head
- torso
- upper/lower arms
- upper/lower legs
- hands/feet
- antenna or character-specific appendages

The first app version stores bone names and rotations in scene JSON. A later version can attach deform meshes or sprite-part images to bones.

## Scene File

Prototype scene:

- `storybook_scenes/book01_password_dragon/page_004.scene.json`

Layer transform fields:

- `x`, `y`: normalized page coordinates from 0 to 1
- `width`, `height`: normalized layer box size
- `scale`: additional layer scale
- `rotation`: degrees
- `opacity`: 0 to 1
- `z_index`: layer stack order

## Web App Slice

Current prototype route:

- `/story-maker`

Initial features:

- view a page scene graph
- render layers in stack order
- select and drag layers
- edit layer transform values
- inspect character rig bones
- copy scene JSON

## Next Build Steps

- TODO: Add save/update scene API.
- TODO: Add layer import from generated transparent PNG assets.
- TODO: Generate clean alpha cutouts for Niko and supporting characters.
- TODO: Add bone handles directly on the stage.
- TODO: Add pose presets such as walking, waving, thinking, pointing, comforting, celebrating.
- TODO: Export composed page PNG at 2625 x 2625 and production PDF.
- TODO: Export layered handoff package for Affinity Publisher.
