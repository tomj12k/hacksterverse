from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import pytest
import yaml
from PIL import Image

from hackster_studio.automation.pipeline import BookBuildPipeline, BuildOptions
from hackster_studio.automation.quality_checks import validate_image
from hackster_studio.automation.comfyui_engine import default_flux_workflow, prepare_workflow
import hackster_studio.automation.pipeline as pipeline_module


def test_one_command_build_creates_book_folders_pages_prompts_and_pdf(tmp_path: Path) -> None:
    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"
    pipeline = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(generate_images=False, build_pdf=True),
    )

    result = pipeline.run()

    assert (book_yaml.parent / "pages").exists()
    assert len(list((book_yaml.parent / "pages").glob("page_*.yaml"))) == 32
    assert len(list((book_yaml.parent / "prompts").glob("page_*.md"))) == 32
    assert result.pdf_path is not None
    assert result.pdf_path.exists()
    assert (book_yaml.parent / "review" / "page_001_review.md").exists()
    assert (book_yaml.parent / "affinity_package" / "page_001" / "layout.json").exists()


def test_pdf_builds_with_placeholders_when_images_are_missing(tmp_path: Path) -> None:
    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"
    result = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(generate_images=False, build_pdf=True, limit_pages=2),
    ).run()

    assert result.pdf_path is not None
    assert result.pdf_path.exists()
    assert result.pdf_path.stat().st_size > 0


def test_production_pdf_builds_with_placeholders_when_images_are_missing(tmp_path: Path) -> None:
    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"
    result = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(generate_images=False, build_production_pdf=True, limit_pages=2),
    ).run()

    assert result.production_pdf_path is not None
    assert result.production_pdf_path.exists()
    assert result.production_pdf_path.stat().st_size > 0


def test_idml_package_builds_for_affinity_handoff(tmp_path: Path) -> None:
    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"
    result = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(generate_images=False, build_idml=True, limit_pages=2),
    ).run()

    assert result.idml_path is not None
    assert result.idml_path.exists()
    with zipfile.ZipFile(result.idml_path) as package:
        names = set(package.namelist())

    assert "mimetype" in names
    assert "designmap.xml" in names
    assert "MasterSpreads/MasterSpread_A.xml" in names
    assert "Resources/Styles.xml" in names
    assert "Spreads/Spread_001.xml" in names
    assert "Stories/Story_001.xml" in names
    assert "XML/BackingStory.xml" in names
    with zipfile.ZipFile(result.idml_path) as package:
        for name in names:
            if name.endswith(".xml"):
                ET.fromstring(package.read(name))
        designmap = ET.fromstring(package.read("designmap.xml"))
    assert designmap.tag == "Document"


def test_validation_catches_low_res_images(tmp_path: Path) -> None:
    image_path = tmp_path / "low_res.png"
    Image.new("RGB", (1000, 1000), "white").save(image_path)

    result = validate_image(1, image_path, (2625, 2625))

    assert result.pass_fail is False
    assert result.exists is True
    assert result.meets_resolution is False


def test_dry_run_does_not_call_openai_api(tmp_path: Path, monkeypatch) -> None:
    called = False

    def fake_generate_image(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("OpenAI should not be called during dry-run")

    monkeypatch.setattr(pipeline_module, "generate_image", fake_generate_image)
    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"
    result = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(generate_images=True, build_pdf=True, dry_run=True),
    ).run()

    assert called is False
    assert result.page_count == 32
    assert not book_yaml.exists()


def test_comfyui_workflow_injects_positive_prompt_and_output_prefix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COMFYUI_UNET", "flux1-schnell.safetensors")
    monkeypatch.setenv("COMFYUI_OUTPUT_PREFIX", "hackster_test")
    workflow = prepare_workflow(
        default_flux_workflow(),
        "small friendly learning robot in Cyber Forest",
        tmp_path / "page_001.png",
    )

    assert workflow["1"]["inputs"]["unet_name"] == "flux1-schnell.safetensors"
    assert workflow["5"]["inputs"]["clip_l"] == "small friendly learning robot in Cyber Forest"
    assert workflow["5"]["inputs"]["t5xxl"] == "small friendly learning robot in Cyber Forest"
    assert workflow["11"]["inputs"]["filename_prefix"] == "hackster_test/page_001"


def test_comfyui_image_generation_releases_dgx_planner_first(tmp_path: Path, monkeypatch) -> None:
    events: list[str] = []

    def fake_release(*args, **kwargs) -> bool:
        events.append("release")
        return True

    def fake_generate_comfyui(prompt: str, output_path: Path) -> Path:
        events.append("generate")
        Image.new("RGB", (2688, 2688), "white").save(output_path, dpi=(300, 300))
        return output_path

    monkeypatch.setattr(pipeline_module, "release_dgx_planner_for_images", fake_release)
    monkeypatch.setattr(pipeline_module, "generate_image_comfyui", fake_generate_comfyui)

    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"
    result = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(generate_images=True, image_backend="comfyui", limit_pages=1, generate_character_references=False),
    ).run()

    assert events[:2] == ["release", "generate"]
    assert len(result.images) == 1
    assert not result.errors


def test_comfyui_image_generation_can_skip_dgx_profile_handoff(tmp_path: Path, monkeypatch) -> None:
    events: list[str] = []

    def fake_release(*args, **kwargs) -> bool:
        events.append("release")
        return True

    def fake_generate_comfyui(prompt: str, output_path: Path) -> Path:
        events.append("generate")
        Image.new("RGB", (2688, 2688), "white").save(output_path, dpi=(300, 300))
        return output_path

    monkeypatch.setattr(pipeline_module, "release_dgx_planner_for_images", fake_release)
    monkeypatch.setattr(pipeline_module, "generate_image_comfyui", fake_generate_comfyui)

    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"
    result = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(
            generate_images=True,
            image_backend="comfyui",
            limit_pages=1,
            manage_dgx_image_profile=False,
            generate_character_references=False,
        ),
    ).run()

    assert events == ["generate"]
    assert len(result.images) == 1
    assert not result.errors


def test_comfyui_image_generation_reports_page_progress(tmp_path: Path, monkeypatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    def fake_release(*args, **kwargs) -> bool:
        return True

    def fake_generate_comfyui(prompt: str, output_path: Path) -> Path:
        Image.new("RGB", (2688, 2688), "white").save(output_path, dpi=(300, 300))
        return output_path

    monkeypatch.setattr(pipeline_module, "release_dgx_planner_for_images", fake_release)
    monkeypatch.setattr(pipeline_module, "generate_image_comfyui", fake_generate_comfyui)

    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"
    result = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(
            generate_images=True,
            image_backend="comfyui",
            limit_pages=2,
            generate_character_references=False,
            progress_callback=lambda event, payload: events.append((event, payload)),
        ),
    ).run()

    started = [payload for event, payload in events if event == "image_page_started"]
    done = [payload for event, payload in events if event == "image_page_done"]

    assert len(result.images) == 2
    assert [payload["page_number"] for payload in started] == [1, 2]
    assert [payload["total_pages"] for payload in done] == [2, 2]
    assert any(event == "images_done" for event, _ in events)


def test_full_image_generation_requires_approved_pilot_page(tmp_path: Path, monkeypatch) -> None:
    called = False

    def fake_generate_image(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Image generation should be blocked by the production gate")

    monkeypatch.setattr(pipeline_module, "generate_image", fake_generate_image)
    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"

    with pytest.raises(RuntimeError, match="production image generation is blocked"):
        BookBuildPipeline(
            book_yaml=book_yaml,
            options=BuildOptions(generate_images=True, image_backend="openai"),
        ).run()

    assert called is False
    assert (book_yaml.parent / "reports" / "production_gate_report.md").exists()


def test_full_image_generation_runs_after_gate_passes(tmp_path: Path, monkeypatch) -> None:
    def fake_generate_image(prompt: str, output_path: Path, model: str) -> Path:
        Image.new("RGB", (2688, 2688), "white").save(output_path, dpi=(300, 300))
        return output_path

    monkeypatch.setattr(pipeline_module, "generate_image", fake_generate_image)
    book_yaml = tmp_path / "books" / "book01_password_dragon" / "book.yaml"

    BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(generate_images=False, limit_pages=1),
    ).run()
    Image.new("RGB", (2688, 2688), "white").save(
        book_yaml.parent / "illustrations" / "page_001.png",
        dpi=(300, 300),
    )
    page_path = book_yaml.parent / "pages" / "page_001.yaml"
    page = yaml.safe_load(page_path.read_text(encoding="utf-8"))
    page["approval_status"] = "approved"
    page_path.write_text(yaml.safe_dump(page, sort_keys=False), encoding="utf-8")

    result = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(generate_images=True, image_backend="openai"),
    ).run()

    assert result.page_count == 32
    assert len(result.images) == 32
    assert not result.errors


def test_page_payload_handles_page_beyond_book01_plan(tmp_path: Path) -> None:
    """Pages outside BOOK01_PAGE_PLAN must not KeyError (multi-book robustness)."""
    book_yaml = tmp_path / "books" / "samurai_splat_01" / "book.yaml"
    pipeline = BookBuildPipeline(
        book_yaml=book_yaml,
        options=BuildOptions(generate_images=False),
    )
    payload = pipeline._page_payload({"hidden_objects": []}, 99)
    assert payload["page_number"] == 99
    assert payload["page_type"] == "story"
    assert payload["scene_title"] == "Page 99"
