#!/usr/bin/env bash
#
# DGX LoRA training launcher invoked by Hackster Studio when you click
# "Process Selected Set Now" (with >= HACKSTER_LORA_MIN_IMAGES examples selected).
#
# Hackster Studio sets these env vars before calling this script:
#   HACKSTER_CHARACTER_SLUG        - e.g. samurai_splat
#   HACKSTER_CHARACTER_NAME        - e.g. Samurai Splat
#   HACKSTER_LORA_DATASET_MANIFEST - absolute path to dataset_manifest.json
#                                    (image paths + captions for the selected set)
#   HACKSTER_LORA_OUTPUT_DIR       - absolute path to write the trained LoRA into
#
# To train for real, set HACKSTER_DGX_LORA_TRAINER_CMD to your DGX trainer
# invocation (kohya sd-scripts FLUX branch, ai-toolkit, SimpleTuner, or a
# ComfyUI TrainLoraNode workflow runner). It runs with the env vars above set,
# so reference them inside your command. Until then this is a safe dry-run that
# records exactly what it would do.
set -uo pipefail

SLUG="${HACKSTER_CHARACTER_SLUG:-unknown}"
NAME="${HACKSTER_CHARACTER_NAME:-$SLUG}"
MANIFEST="${HACKSTER_LORA_DATASET_MANIFEST:-}"
OUTDIR="${HACKSTER_LORA_OUTPUT_DIR:-}"
SSH_HOST="${HACKSTER_DGX_SSH_HOST:-sync-spark-d1a9_local}"
TRAINER_CMD="${HACKSTER_DGX_LORA_TRAINER_CMD:-}"

mkdir -p "$OUTDIR" 2>/dev/null || true
IMAGES="?"
if [ -n "$MANIFEST" ] && [ -f "$MANIFEST" ]; then
  IMAGES="$(grep -c '"path"' "$MANIFEST" 2>/dev/null || echo '?')"
fi

echo "[$(date -u +%FT%TZ)] LoRA training launch: ${NAME} (${SLUG})"
echo "  dataset manifest : ${MANIFEST}"
echo "  output dir       : ${OUTDIR}"
echo "  dataset images   : ${IMAGES}"
echo "  DGX ssh host      : ${SSH_HOST}"

if [ -z "$TRAINER_CMD" ]; then
  echo "  STATUS: dry-run — HACKSTER_DGX_LORA_TRAINER_CMD is not set, so no real training ran."
  echo "  Configure it (in .env) to your DGX FLUX LoRA trainer, e.g.:"
  echo "    HACKSTER_DGX_LORA_TRAINER_CMD='ssh ${SSH_HOST} bash -lc \"cd ~/ai-toolkit && python run.py --dataset \$HACKSTER_LORA_DATASET_MANIFEST --output \$HACKSTER_LORA_OUTPUT_DIR --trigger ${SLUG}_character\"'"
  echo "  The dataset manifest + output dir are exported above; reference them in your command."
  exit 0
fi

echo "  STATUS: invoking configured trainer..."
HACKSTER_CHARACTER_SLUG="$SLUG" \
HACKSTER_CHARACTER_NAME="$NAME" \
HACKSTER_LORA_DATASET_MANIFEST="$MANIFEST" \
HACKSTER_LORA_OUTPUT_DIR="$OUTDIR" \
HACKSTER_DGX_SSH_HOST="$SSH_HOST" \
bash -c "$TRAINER_CMD"
code=$?
echo "[$(date -u +%FT%TZ)] trainer exited with code ${code}"
exit "$code"
