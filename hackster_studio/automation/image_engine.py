"""OpenAI Image API wrapper used only when image generation is explicitly enabled."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def generate_image(prompt: str, output_path: Path, model: str) -> Path:
    """Generate one image with OpenAI and save it as a PNG.

    This function intentionally reads credentials from the environment and never
    hardcodes secrets. It expects a base64 image response, which avoids a second
    network download step.
    """
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env, add your key, "
            "or rerun with --no-images."
        )

    image_size = os.getenv("OPENAI_IMAGE_SIZE", "1024x1024")
    client = OpenAI(api_key=api_key)
    response = client.images.generate(
        model=model,
        prompt=prompt,
        size=image_size,
        n=1,
        response_format="b64_json",
    )

    if not response.data or not response.data[0].b64_json:
        raise RuntimeError("OpenAI Image API returned no base64 image data.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(response.data[0].b64_json))
    return output_path

