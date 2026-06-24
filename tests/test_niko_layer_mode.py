from pathlib import Path

from hackster_studio.automation.pipeline import BookBuildPipeline, BuildOptions, default_book_data


def test_posable_layer_niko_is_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HACKSTER_NIKO_LAYER_MODE", raising=False)
    pipeline = BookBuildPipeline(tmp_path / "book.yaml", BuildOptions())

    page = pipeline._page_payload(default_book_data(), 4)

    assert page["niko_layer_mode"] == "posable_layer"
    assert page["niko_pose"] == "walk_front"
    assert "background_direction" in page
    assert "Hackster Niko" in page["characters"]


def test_locked_overlay_is_opt_in(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HACKSTER_NIKO_LAYER_MODE", "locked_overlay")
    pipeline = BookBuildPipeline(tmp_path / "book.yaml", BuildOptions())

    page = pipeline._page_payload(default_book_data(), 4)

    assert page["niko_layer_mode"] == "locked_overlay"
    assert page["niko_pose"] == "walk_front"
    assert "background_direction" in page


def test_non_hackster_books_do_not_get_niko_layer_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HACKSTER_NIKO_LAYER_MODE", raising=False)
    pipeline = BookBuildPipeline(tmp_path / "book.yaml", BuildOptions())
    book = default_book_data() | {
        "title": "Samurai Splat",
        "slug": "samurai_splat_01",
        "niko_layer_mode": "posable_layer",
    }

    page = pipeline._page_payload(book, 4)

    assert "niko_layer_mode" not in page
    assert "background_direction" not in page


def test_build_options_page_range_selects_later_pages(tmp_path: Path) -> None:
    pipeline = BookBuildPipeline(
        tmp_path / "book.yaml",
        BuildOptions(page_from=5, page_to=7),
    )
    pages = [pipeline._page_payload(default_book_data(), page) for page in range(1, 10)]

    selected = pipeline._limit(pages)

    assert [page["page_number"] for page in selected] == [5, 6, 7]
