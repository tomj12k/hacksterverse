# Model Handoff

- script_llm: Qwen3.6 or Llama 4
- keyframes: FLUX.1-dev or SDXL illustration checkpoint
- video: Wan 2.2 I2V/TI2V
- dialogue: Chatterbox TTS or CosyVoice
- lip_sync: LatentSync, with MuseTalk for fast talking-head tests
- music: ACE-Step 1.5
- sfx: AudioLDM2, with Stable Audio Open as a gated optional upgrade
- assembly: DaVinci Resolve, Premiere, or ffmpeg

## Recommended Order

1. Generate or approve one keyframe per shot.
2. Run image-to-video from approved keyframes.
3. Generate dialogue audio from `audio/dialogue/*.txt`.
4. Lip-sync only dialogue shots.
5. Generate music bed and SFX, then mix per shot.
6. Assemble approved clips using `edit/edit_decision_list.csv`.
