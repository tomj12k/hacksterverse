#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p renders/final

ffmpeg -y \
  -f concat \
  -safe 0 \
  -i edit/ffmpeg_concat.txt \
  -r 24 \
  -s 1920x1080 \
  -c:v libx264 \
  -pix_fmt yuv420p \
  -movflags +faststart \
  renders/final/password_dragon_teaser_picture_lock.mp4

echo "Wrote renders/final/password_dragon_teaser_picture_lock.mp4"
echo "Mix final music/dialogue/SFX in your editor, or mux a final WAV with:"
echo "ffmpeg -i renders/final/password_dragon_teaser_picture_lock.mp4 -i audio/mixes/final_mix.wav -c:v copy -c:a aac renders/final/password_dragon_teaser_final.mp4"
