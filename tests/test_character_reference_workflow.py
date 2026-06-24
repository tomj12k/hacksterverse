from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from PIL import Image, ImageDraw

from hackster_studio.automation.comfyui_engine import prepare_workflow
from hackster_studio.automation import character_reference as character_reference_module
from hackster_studio.automation.character_reference import generate_character_reference_packs
from hackster_studio.services import character_training as character_training_module
from hackster_studio.services.character_training import (
    active_lora_for_character,
    character_training_bench,
    delete_character_image,
    delete_character_images,
    delete_reference_pack,
    lora_environment_for_character,
    prepare_lora_dataset,
    process_training_selection,
    save_lora_settings,
    save_training_selection,
)
from hackster_studio.config import PROJECT_ROOT


def _write_nonblank_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((32, 32, 224, 224), fill=(70, 199, 255))
    draw.ellipse((80, 56, 176, 152), fill=(57, 74, 99))
    image.save(path)


def test_character_reference_pack_generates_versioned_assets(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []

    def fake_generate_image(prompt: str, output_path: Path, **kwargs) -> Path:
        assert "Character reference pack image" in prompt
        calls.append(output_path)
        _write_nonblank_png(output_path)
        return output_path

    monkeypatch.setattr(character_reference_module, "generate_image_comfyui", fake_generate_image)
    monkeypatch.setenv("HACKSTER_CHARACTER_MIN_PIXELS", "64")
    book = {
        "title": "Samurai Splat",
        "slug": "samurai_splat",
        "character_layer_mode": "separate_layers",
        "global_illustration_style": "bold cinematic comic strip storybook art",
        "planner_brief": {
            "focus_characters": ["Samurai Splat", "Shotgun Bob"],
            "focus_items": ["Bamboo Bucket"],
            "reference_notes": "Samurai Splat keeps the same helmet and paint-splatter robe.",
        },
    }
    pages = [
        {"page_number": 1, "characters": ["Samurai Splat"]},
        {"page_number": 2, "characters": ["Shotgun Bob", "Samurai Splat"]},
    ]

    result = generate_character_reference_packs(
        book_slug="samurai_splat",
        book=book,
        pages=pages,
        project_root=tmp_path,
        manage_dgx_image_profile=False,
    )

    assert result.ready is True
    assert result.character_count == 2
    assert result.image_count == 32
    assert len(calls) == 32
    samurai_root = tmp_path / "assets" / "layers" / "characters" / "samurai_splat"
    assert (samurai_root / "references" / "samurai_splat_turnaround_front.png").exists()
    assert (samurai_root / "expressions" / "samurai_splat_expression_happy.png").exists()
    assert (samurai_root / "poses" / "samurai_splat_pose_pointing.png").exists()
    assert (samurai_root / "character_reference_pack.json").exists()
    assert (samurai_root / "qa" / "character_reference_qa.md").exists()
    with Image.open(samurai_root / "references" / "samurai_splat_turnaround_front.png") as generated:
        assert generated.mode == "RGBA"
        assert generated.getpixel((0, 0))[3] == 0


def test_character_reference_pack_honors_requested_image_count(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []

    def fake_generate_image(prompt: str, output_path: Path, **kwargs) -> Path:
        if "sample variant 004" in prompt:
            assert "Keep identity, proportions, silhouette, colors, outfit" in prompt
        calls.append(output_path)
        _write_nonblank_png(output_path)
        return output_path

    monkeypatch.setattr(character_reference_module, "generate_image_comfyui", fake_generate_image)
    monkeypatch.setenv("HACKSTER_CHARACTER_MIN_PIXELS", "64")

    result = generate_character_reference_packs(
        book_slug="samurai_splat",
        book={
            "title": "Samurai Splat",
            "slug": "samurai_splat",
            "planner_brief": {"focus_characters": ["Samurai Splat"]},
        },
        pages=[],
        project_root=tmp_path,
        image_count_per_character=20,
        manage_dgx_image_profile=False,
    )

    root = tmp_path / "assets" / "layers" / "characters" / "samurai_splat"
    manifest = json.loads((root / "character_reference_pack.json").read_text(encoding="utf-8"))

    assert result.ready is True
    assert result.image_count == 20
    assert len(calls) == 20
    assert (root / "samples" / "samurai_splat_sample_variant_004.png").exists()
    assert manifest["requested_image_count"] == 20
    assert manifest["image_count"] == 20


def test_separate_layer_prompt_creates_character_free_background_plate() -> None:
    env = Environment(
        loader=FileSystemLoader(PROJECT_ROOT / "hackster_studio" / "prompt_templates"),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("book_page_illustration.md.j2")

    prompt = template.render(
        book={
            "title": "Samurai Splat",
            "character_layer_mode": "separate_layers",
            "global_illustration_style": "bold cinematic comic strip storybook art",
        },
        page={
            "illustration_direction": "A moonlit dojo after a paint accident.",
            "environment": "Dojo",
            "emotion": "funny chaos",
            "camera": "wide comic establishing shot",
            "text_safe_area": "top third clear",
        },
        characters=["Samurai Splat", "Shotgun Bob"],
        hidden_objects=["Paint Star"],
        niko_consistency_phrase="",
    )

    assert "character-free background plate" in prompt
    assert "Characters planned as separate editable layers: Samurai Splat, Shotgun Bob." in prompt
    assert "Absolute visual exclusions: no visible story characters" in prompt
    assert "Characters in the scene: Samurai Splat" not in prompt


def test_character_training_manifest_selects_examples_and_prepares_lora(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(character_training_module, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(character_training_module, "PROJECT_ROOT", tmp_path)
    root = tmp_path / "assets" / "layers" / "characters" / "samurai_splat"
    for index in range(1, 4):
        _write_nonblank_png(root / "references" / f"samurai_splat_turnaround_{index}.png")

    selected = [
        "assets/layers/characters/samurai_splat/references/samurai_splat_turnaround_1.png",
        "assets/layers/characters/samurai_splat/references/samurai_splat_turnaround_2.png",
    ]
    save_training_selection("samurai_splat", selected, name="Samurai Splat")
    manifest = prepare_lora_dataset("samurai_splat", name="Samurai Splat")
    bench = character_training_bench("Samurai Splat", "samurai_splat")

    assert manifest["status"] == "needs_more_examples"
    assert manifest["dataset_manifest"] == "assets/layers/characters/samurai_splat/lora/dataset_manifest.json"
    assert manifest["training_request"] == "assets/layers/characters/samurai_splat/lora/lora_training_request.yaml"
    assert bench["selected_count"] == 2
    assert bench["images"][0]["selected"] is True


def test_process_training_selection_auto_prepares_dataset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(character_training_module, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(character_training_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("HACKSTER_LORA_MIN_IMAGES", "2")
    monkeypatch.delenv("HACKSTER_DGX_LORA_TRAIN_COMMAND", raising=False)
    root = tmp_path / "assets" / "layers" / "characters" / "samurai_splat"
    for index in range(1, 3):
        _write_nonblank_png(root / "references" / f"samurai_splat_turnaround_{index}.png")

    selected = [
        "assets/layers/characters/samurai_splat/references/samurai_splat_turnaround_1.png",
        "assets/layers/characters/samurai_splat/references/samurai_splat_turnaround_2.png",
    ]
    manifest = process_training_selection("samurai_splat", selected, name="Samurai Splat")

    assert manifest["status"] == "ready_to_train"
    assert manifest["dataset_manifest"] == "assets/layers/characters/samurai_splat/lora/dataset_manifest.json"
    assert manifest["training_request"] == "assets/layers/characters/samurai_splat/lora/lora_training_request.yaml"
    assert "automatically" in manifest["last_training_message"]


def test_delete_character_image_removes_file_and_selection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(character_training_module, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(character_training_module, "PROJECT_ROOT", tmp_path)
    image_path = tmp_path / "assets" / "layers" / "characters" / "samurai_splat" / "references" / "front.png"
    _write_nonblank_png(image_path)
    rel = "assets/layers/characters/samurai_splat/references/front.png"
    save_training_selection("samurai_splat", [rel], name="Samurai Splat")

    manifest = delete_character_image("samurai_splat", rel, name="Samurai Splat")

    assert not image_path.exists()
    assert manifest["selected_images"] == []
    assert manifest["status"] == "needs_examples"


def test_delete_character_images_removes_selected_batch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(character_training_module, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(character_training_module, "PROJECT_ROOT", tmp_path)
    root = tmp_path / "assets" / "layers" / "characters" / "samurai_splat"
    first = root / "references" / "front.png"
    second = root / "poses" / "wave.png"
    third = root / "identity" / "anchor.png"
    for image_path in (first, second, third):
        _write_nonblank_png(image_path)
    selected = [
        "assets/layers/characters/samurai_splat/references/front.png",
        "assets/layers/characters/samurai_splat/poses/wave.png",
        "assets/layers/characters/samurai_splat/identity/anchor.png",
    ]
    save_training_selection("samurai_splat", selected, name="Samurai Splat")

    manifest = delete_character_images("samurai_splat", selected[:2], name="Samurai Splat")

    assert not first.exists()
    assert not second.exists()
    assert third.exists()
    assert manifest["selected_images"] == [selected[2]]
    assert manifest["status"] == "examples_selected"


def test_delete_reference_pack_preserves_lora_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(character_training_module, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(character_training_module, "PROJECT_ROOT", tmp_path)
    root = tmp_path / "assets" / "layers" / "characters" / "samurai_splat"
    _write_nonblank_png(root / "references" / "front.png")
    _write_nonblank_png(root / "expressions" / "happy.png")
    _write_nonblank_png(root / "poses" / "stand.png")
    _write_nonblank_png(root / "samples" / "variant.png")
    (root / "prompts").mkdir(parents=True)
    (root / "prompts" / "front.md").write_text("prompt", encoding="utf-8")
    (root / "qa").mkdir(parents=True)
    (root / "qa" / "character_reference_qa.md").write_text("qa", encoding="utf-8")
    (root / "character_reference_pack.json").write_text("{}", encoding="utf-8")
    (root / "lora").mkdir(parents=True)
    (root / "lora" / "training_manifest.json").write_text("{}", encoding="utf-8")

    delete_reference_pack("samurai_splat", name="Samurai Splat")

    assert not (root / "references").exists()
    assert not (root / "expressions").exists()
    assert not (root / "poses").exists()
    assert not (root / "samples").exists()
    assert not (root / "prompts").exists()
    assert not (root / "qa").exists()
    assert not (root / "character_reference_pack.json").exists()
    assert (root / "lora" / "training_manifest.json").exists()


def test_active_lora_sets_comfyui_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(character_training_module, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(character_training_module, "PROJECT_ROOT", tmp_path)

    save_lora_settings(
        "samurai_splat",
        name="Samurai Splat",
        lora_name="samurai_splat_flux_lora.safetensors",
        trigger="samurai_splat_character",
    )

    assert active_lora_for_character("samurai_splat")["name"] == "samurai_splat_flux_lora.safetensors"
    with lora_environment_for_character("samurai_splat"):
        import os

        assert os.getenv("COMFYUI_LORA_NAME") == "samurai_splat_flux_lora.safetensors"


def test_comfyui_workflow_injects_lora_loader(monkeypatch) -> None:
    monkeypatch.setenv("COMFYUI_LORA_NAME", "samurai_splat_flux_lora.safetensors")
    monkeypatch.setenv("COMFYUI_LORA_STRENGTH_MODEL", "0.7")
    monkeypatch.setenv("COMFYUI_LORA_STRENGTH_CLIP", "0.6")
    workflow = {
        "1": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": ""},
            "_meta": {"title": "Positive Prompt"},
        },
        "2": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["0", 0],
                "clip": ["0", 1],
                "lora_name": "old.safetensors",
                "strength_model": 1,
                "strength_clip": 1,
            },
        },
    }

    prepared = prepare_workflow(workflow, "Samurai Splat action pose", Path("/tmp/out.png"))

    assert prepared["2"]["inputs"]["lora_name"] == "samurai_splat_flux_lora.safetensors"
    assert prepared["2"]["inputs"]["strength_model"] == 0.7
    assert prepared["2"]["inputs"]["strength_clip"] == 0.6
