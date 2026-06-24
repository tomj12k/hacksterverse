# Hackster Niko Movie Pipeline

This workflow turns a Hackster Niko story into an editable, shot-based movie package. It is designed for local/DGX generation, human review, and conventional editing.

## Recommended Stack

- Script and shot planning: Qwen3.6, Llama 4, or another strong local LLM.
- Keyframes: FLUX.1-dev, SDXL, or the approved Hackster Niko illustration workflow in ComfyUI.
- Video: Wan 2.2 image-to-video or text/image-to-video.
- Dialogue: Chatterbox TTS or CosyVoice.
- Lip-sync: LatentSync for final shots; MuseTalk for quick talking-head tests.
- Music: ACE-Step 1.5.
- SFX and ambience: AudioLDM2. Stable Audio Open is a gated optional upgrade if your Hugging Face token has access.
- Editing: DaVinci Resolve, Premiere, Final Cut, or `ffmpeg`.

## Build The Package

```bash
python -m hackster_studio.cli build-movie-package movies/password_dragon_teaser/movie.yaml
```

For a small test:

```bash
python -m hackster_studio.cli build-movie-package movies/password_dragon_teaser/movie.yaml --limit-shots 3 --force
```

The command creates:

- `shots/` - one YAML file per shot.
- `prompts/keyframes/` - still-image prompts for approved keyframes.
- `prompts/video/` - image-to-video prompts for Wan/Cosmos/Hunyuan workflows.
- `audio/dialogue/` - TTS scripts per shot.
- `audio/sfx/` - SFX cue notes per shot.
- `audio/music/music_brief.md` - score generation brief.
- `renders/keyframes/` - approved stills go here.
- `renders/video_raw/` - raw model video clips go here.
- `renders/video_lipsynced/` - approved picture clips go here after lip-sync, or copied from raw for silent shots.
- `edit/` - EDL, concat file, assembly script, editor checklist.
- `review/` - shot review checklists.
- `reports/` - model handoff and build report.

## Production Order

1. Approve the shot list in `movie.yaml` and `shots/*.yaml`.
2. Generate one keyframe per shot from `prompts/keyframes/*.md`.
3. Review character continuity before animating anything.
4. Generate video clips from approved keyframes using `prompts/video/*.md`.
5. Generate dialogue WAVs from `audio/dialogue/*.txt`.
6. Lip-sync dialogue shots and save the approved clips to `renders/video_lipsynced/`. For silent shots, copy the approved raw clip into this folder with the expected `SH###_lipsync.mp4` name so the edit list has one consistent source.
7. Generate or record SFX and music, then make per-shot mixes in `audio/mixes/`.
8. Edit from `edit/edit_decision_list.csv`.
9. Render a picture-lock review export.
10. Do the final sound mix and export the deliverable.

## File Naming

Keep every shot sortable by shot ID:

```text
SH010_keyframe.png
SH010_raw.mp4
SH010_lipsync.mp4
SH010_dialogue.wav
SH010_mix.wav
```

Do not overwrite approved files. If a shot needs a new attempt, use a suffix:

```text
SH010_raw_v002.mp4
SH010_lipsync_v002.mp4
```

Then update `edit/edit_decision_list.csv` or `edit/ffmpeg_concat.txt`.

## DGX / ComfyUI Handoff

Use the existing ComfyUI DGX setup in `docs/COMFYUI_DGX_INTEGRATION.md` for stills and video workflows. For Wan 2.2, the simplest production pattern is:

1. Load the approved keyframe.
2. Paste the matching `prompts/video/SH###_video.md` prompt.
3. Set duration near the shot target.
4. Render at 24 fps or the closest model-supported rate.
5. Save raw clips to `renders/video_raw/`.

For dialogue shots, run lip-sync after the video clip and dialogue WAV exist.

## Review Gates

Before a shot is approved:

- Niko must match the HN-01 locked design.
- Niko must not have a mouth, nose, tail, ears, fur, claws, wings, or extra limbs.
- There must be no readable passwords, captions, UI text, fake writing, logos, or watermarks.
- The tone must stay warm, clever, playful, reassuring, and child-safe.
- Dialogue must be intelligible.
- Lip-sync must be checked when the shot contains spoken character dialogue.

## Assembly

The generated `edit/assemble_ffmpeg.sh` can make a basic picture-lock export after approved lip-synced clips exist:

```bash
cd movies/password_dragon_teaser
./edit/assemble_ffmpeg.sh
```

For real editorial, import `edit/edit_decision_list.csv`, all approved clips, and all WAV files into DaVinci Resolve or your preferred editor. Treat the `ffmpeg` script as a quick proof, not the final creative edit.
