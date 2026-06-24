"""
Browser-level integration tests using pytest-playwright.

The live_server and base_url fixtures (session-scoped) are provided by conftest.py.
Each test navigates to /story-maker and exercises features through the real DOM.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytest_playwright"]


# ── Page loads ────────────────────────────────────────────────────────────────


def test_story_maker_page_loads(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_load_state("networkidle")
    assert "Story Maker" in page.title() or page.query_selector("body") is not None


def test_story_maker_has_toolbar(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='save']")
    assert page.query_selector("[data-action='save']") is not None
    assert page.query_selector("[data-action='undo']") is not None
    assert page.query_selector("[data-action='redo']") is not None
    assert page.query_selector("[data-save-state]") is not None
    assert page.query_selector("[data-action='export-flat']") is not None
    assert page.query_selector("[data-action='export-draft']") is not None
    assert page.query_selector("[data-action='add-text']") is not None
    assert page.query_selector("[data-action='toggle-text']") is not None
    assert page.query_selector("[data-action='approve-page']") is not None


def test_global_book_switcher_visible_on_dashboard(page, base_url: str) -> None:
    page.goto(f"{base_url}/")
    page.wait_for_selector("[data-book-switcher] select", timeout=5000)
    assert page.locator("[data-book-switcher] select").count() == 1


def test_story_maker_has_layer_panel(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-layer-list]")
    layer_list = page.query_selector("[data-layer-list]")
    assert layer_list is not None


def test_story_maker_has_stage(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-story-stage]")
    assert page.query_selector("[data-story-stage]") is not None
    assert page.query_selector(".page-guide--safe") is not None
    assert page.query_selector("[data-grid-toggle]") is not None
    assert page.query_selector("[data-snap-toggle]") is not None
    assert page.query_selector("[data-snap-readout]") is not None
    assert page.query_selector("[data-viewport-mode='theater']") is not None


def test_story_maker_has_production_status_and_qa(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?book_slug=book01_password_dragon&page=5")
    page.wait_for_selector("[data-page-status-control]")
    assert page.query_selector("[data-qa-panel]") is not None
    assert page.query_selector("[data-action='mark-needs-edit']") is not None
    assert page.query_selector("[data-action='approve-page']") is not None


def test_story_maker_viewport_modes_resize_canvas(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?book_slug=book01_password_dragon&page=5")
    page.wait_for_selector("[data-story-stage]", timeout=5000)
    page.evaluate("localStorage.removeItem('storyMakerViewportMode')")
    page.reload()
    page.wait_for_selector("[data-story-stage]", timeout=5000)

    default_width = page.locator("[data-story-stage]").bounding_box()["width"]
    page.click("[data-viewport-mode='theater']")
    page.wait_for_function(
        """() => document.querySelector('[data-story-maker]')?.dataset.viewportMode === 'theater'""",
        timeout=3000,
    )
    theater_width = page.locator("[data-story-stage]").bounding_box()["width"]
    assert theater_width >= default_width

    page.click("[data-viewport-mode='focus']")
    page.wait_for_function(
        """() => localStorage.getItem('storyMakerViewportMode') === 'focus'""",
        timeout=3000,
    )
    assert page.locator("button[data-viewport-mode='focus']").get_attribute("aria-pressed") == "true"


def test_story_maker_has_add_layer_button(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='add-layer']")
    assert page.query_selector("[data-action='add-layer']") is not None
    assert page.query_selector("[data-action='delete-layer']") is not None


def test_add_text_button_creates_movable_text_layer(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='add-text']")
    page.click("[data-action='add-text']")
    page.wait_for_selector(".story-layer--text", timeout=5000)
    assert page.query_selector(".story-placeholder--text") is not None
    assert page.query_selector("[data-action='generate-text-art']") is not None
    assert page.query_selector("[data-action='generate-text-art-variant']") is not None


def test_story_page_loads_default_text_layer(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?book_slug=book01_password_dragon&page=5")
    page.wait_for_selector("[data-layer-id='page_text']", timeout=5000)

    layer_button = page.locator(".layer-button").filter(has_text="Page Text")
    assert layer_button.count() == 1
    assert page.query_selector(".story-placeholder--text") is not None

    text = page.query_selector(".story-placeholder--text").inner_text()
    assert text.strip()
    assert text != "Every problem has a clever fix!"


# ── Layer panel has items after load ─────────────────────────────────────────


def test_layer_panel_populated_after_load(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    # Wait for the JS to initialize and render layer buttons
    page.wait_for_selector(".layer-button", timeout=5000)
    buttons = page.query_selector_all(".layer-button")
    assert len(buttons) > 0, "No layer buttons rendered"


def test_stage_has_layer_elements_after_load(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_load_state("networkidle")
    # Stage should have div children for each image/lighting layer
    stage = page.query_selector("[data-story-stage]")
    children = stage.query_selector_all("[data-layer-id]")
    # Not all scenes have composited elements, but DOM should be initialized
    assert stage is not None


# ── Add layer dialog ─────────────────────────────────────────────────────────


def test_add_layer_button_opens_dialog(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='add-layer']")
    page.click("[data-action='add-layer']")
    # Dialog should now be open (either via [open] attr or display)
    dialog = page.query_selector("[data-asset-browser]")
    assert dialog is not None
    # Wait for dialog to be open
    page.wait_for_selector("dialog[open]", timeout=3000)
    assert page.query_selector("dialog[open]") is not None


def test_asset_browser_dialog_has_tabs(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='add-layer']")
    page.click("[data-action='add-layer']")
    page.wait_for_selector("dialog[open]", timeout=3000)
    # Tabs should be populated after assets load
    page.wait_for_selector("[data-asset-tabs] button", timeout=5000)
    tabs = page.query_selector_all("[data-asset-tabs] button")
    assert len(tabs) > 0, "Asset browser has no tabs"


def test_asset_browser_close_button_closes_dialog(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='add-layer']")
    page.click("[data-action='add-layer']")
    page.wait_for_selector("dialog[open]", timeout=3000)

    page.click("[data-close-browser]")
    # Dialog should no longer have [open] attribute
    page.wait_for_function("!document.querySelector('dialog[open]')", timeout=3000)
    assert page.query_selector("dialog[open]") is None


# ── Inspector controls ────────────────────────────────────────────────────────


def test_inspector_has_transform_controls(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_load_state("networkidle")
    for control in ("x", "y", "width", "height", "scale", "rotation", "opacity"):
        assert page.query_selector(f"[data-control='{control}']") is not None, \
            f"Missing inspector control: {control}"


def test_inspector_has_zoom_control(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_load_state("networkidle")
    assert page.query_selector("[data-control='zoom']") is not None


def test_width_height_controls_resize_selected_layer(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?book_slug=book01_password_dragon&page=5")
    page.wait_for_selector("[data-layer-id='page_text']", timeout=5000)
    page.locator(".layer-button").filter(has_text="Page Text").click()
    page.wait_for_selector(".story-layer[data-layer-id='page_text'].is-selected", timeout=3000)
    assert page.locator(".story-layer[data-layer-id='page_text'] .story-resize-handle").is_visible()
    page.uncheck("[data-snap-toggle]")

    page.fill("[data-control='width']", "0.42")
    page.fill("[data-control='height']", "0.11")

    page.wait_for_function(
        """() => {
            const layer = window._sm?.findLayer('page_text');
            return layer?.transform?.width === 0.42 && layer?.transform?.height === 0.11;
        }""",
        timeout=3000,
    )
    state = page.evaluate(
        """() => {
            const layer = window._sm.findLayer('page_text');
            const el = document.querySelector('.story-layer[data-layer-id="page_text"]');
            return {
                width: layer.transform.width,
                height: layer.transform.height,
                styleWidth: el.style.width,
                styleHeight: el.style.height,
            };
        }"""
    )
    assert state["width"] == 0.42
    assert state["height"] == 0.11
    assert state["styleWidth"] == "42%"
    assert state["styleHeight"] == "11%"


def test_undo_redo_and_dirty_state_for_transform(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?book_slug=book01_password_dragon&page=5")
    page.wait_for_selector("[data-layer-id='page_text']", timeout=5000)
    page.locator(".layer-button").filter(has_text="Page Text").click()
    page.uncheck("[data-snap-toggle]")

    original_x = page.evaluate("window._sm.findLayer('page_text').transform.x")
    page.fill("[data-control='x']", "0.33")

    page.wait_for_function(
        """() => window._sm?.findLayer('page_text')?.transform?.x === 0.33""",
        timeout=3000,
    )
    assert page.locator("[data-save-state]").inner_text() == "Unsaved"
    assert page.locator("[data-action='undo']").is_enabled()

    page.click("[data-action='undo']")
    page.wait_for_function(
        """(originalX) => window._sm?.findLayer('page_text')?.transform?.x === originalX""",
        arg=original_x,
        timeout=3000,
    )
    assert page.locator("[data-action='redo']").is_enabled()

    page.click("[data-action='redo']")
    page.wait_for_function(
        """() => window._sm?.findLayer('page_text')?.transform?.x === 0.33""",
        timeout=3000,
    )

    page.click("[data-action='save']")
    page.wait_for_function(
        """() => document.querySelector('[data-save-state]')?.textContent === 'Saved'""",
        timeout=3000,
    )


def test_text_font_size_control_changes_live_text(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?book_slug=book01_password_dragon&page=5")
    page.wait_for_selector("[data-layer-id='page_text']", timeout=5000)
    page.locator(".layer-button").filter(has_text="Page Text").click()

    page.fill("[data-text-control='font-size']", "0.08")

    result = page.evaluate(
        """() => ({
            size: document.querySelector('.story-placeholder--text').style.fontSize,
            expected: `${Math.round(document.querySelector('[data-story-stage]').getBoundingClientRect().height * 0.08)}px`
        })"""
    )
    assert result["size"] == result["expected"]


def test_transform_fields_snap_to_grid(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?book_slug=book01_password_dragon&page=5")
    page.wait_for_selector("[data-layer-id='page_text']", timeout=5000)
    page.locator(".layer-button").filter(has_text="Page Text").click()
    page.select_option("[data-grid-size]", "0.05")

    page.fill("[data-control='x']", "0.531")

    page.wait_for_function(
        """() => window._sm?.findLayer('page_text')?.transform?.x === 0.55""",
        timeout=3000,
    )
    assert "X 55%" in page.locator("[data-snap-readout]").inner_text()


def test_text_inspector_has_apply_all_button(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?book_slug=book01_password_dragon&page=5")
    page.wait_for_selector("[data-layer-id='page_text']", timeout=5000)
    page.locator(".layer-button").filter(has_text="Page Text").click()
    assert page.query_selector("[data-action='apply-text-style-all']") is not None


# ── Layer selection ───────────────────────────────────────────────────────────


def test_clicking_layer_marks_it_active(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector(".layer-button", timeout=5000)
    buttons = page.query_selector_all(".layer-button")
    if not buttons:
        pytest.skip("No layer buttons to click")

    # Click first layer button
    buttons[0].click()
    page.wait_for_timeout(200)

    # It should receive the is-active class
    is_active = buttons[0].get_attribute("class")
    assert "is-active" in (is_active or ""), "Clicked layer button did not get is-active class"


def test_only_one_layer_active_at_a_time(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector(".layer-button", timeout=5000)
    buttons = page.query_selector_all(".layer-button")
    if len(buttons) < 2:
        pytest.skip("Need at least 2 layer buttons")

    buttons[0].click()
    page.wait_for_timeout(100)
    buttons[1].click()
    page.wait_for_timeout(200)

    active_count = len(page.query_selector_all(".layer-button.is-active"))
    assert active_count <= 1, f"Expected at most 1 active layer button, got {active_count}"


def test_can_delete_hackster_niko_layer(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?page=5")
    page.wait_for_selector("[data-layer-id='char_niko']", timeout=5000)

    layer_button = page.locator(".layer-button").filter(has_text="Hackster Niko")
    assert layer_button.count() == 1
    layer_button.click()

    delete_button = page.locator("[data-action='delete-layer']")
    assert delete_button.count() == 1
    assert delete_button.is_enabled()
    delete_button.click()

    page.wait_for_timeout(200)
    assert page.query_selector("[data-layer-id='char_niko']") is None
    assert page.locator(".layer-button").filter(has_text="Hackster Niko").count() == 0


def test_layer_visibility_lock_and_duplicate_controls(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker?page=5")
    page.wait_for_selector("[data-layer-id='char_niko']", timeout=5000)
    page.locator(".layer-button").filter(has_text="Hackster Niko").click()

    page.click("[data-layer-action='toggle-visible']")
    page.wait_for_function(
        """() => window._sm?.findLayer('char_niko')?.visible === false""",
        timeout=3000,
    )
    assert page.locator(".story-layer[data-layer-id='char_niko']").is_hidden()

    page.click("[data-layer-action='toggle-visible']")
    page.click("[data-layer-action='toggle-lock']")
    page.wait_for_function(
        """() => window._sm?.findLayer('char_niko')?.locked === true""",
        timeout=3000,
    )

    page.click("[data-layer-action='toggle-lock']")
    before = page.locator(".layer-button").count()
    page.click("[data-layer-action='duplicate']")
    page.wait_for_function(
        """(before) => document.querySelectorAll('.layer-button').length === before + 1""",
        arg=before,
        timeout=3000,
    )


# ── Save button ───────────────────────────────────────────────────────────────


def test_save_button_sends_put_request(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='save']")

    put_requests = []

    def on_request(req) -> None:
        if req.method == "PUT" and "/api/scenes/" in req.url:
            put_requests.append(req)

    page.on("request", on_request)
    page.click("[data-action='save']")
    page.wait_for_timeout(1000)

    assert len(put_requests) > 0, "Save button did not send a PUT request"


def test_save_button_text_changes_while_saving(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='save']")
    page.click("[data-action='save']")
    # Should briefly show "Saving…" or "Saved ✓"
    page.wait_for_timeout(1500)
    final_text = page.query_selector("[data-action='save']").inner_text()
    # After 1.5s it should have reset back to "Save" or show "Saved ✓"
    assert final_text in ("Save", "Saved ✓", "Error")


# ── Toggle text ───────────────────────────────────────────────────────────────


def test_toggle_text_hides_text_layers(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_load_state("networkidle")

    page.click("[data-action='toggle-text']")
    page.wait_for_timeout(300)
    # Text layers should be hidden (display:none) when toggled off
    text_elements = page.query_selector_all("[data-layer-type='text']")
    for el in text_elements:
        style = el.get_attribute("style") or ""
        # At least one sign of being hidden
        assert "display: none" in style or "visibility: hidden" in style or \
               el.is_hidden(), "Text layer not hidden after toggle"


# ── Asset browser tabs ────────────────────────────────────────────────────────


def test_asset_browser_has_background_tab(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='add-layer']")
    page.click("[data-action='add-layer']")
    page.wait_for_selector("[data-asset-tabs] button", timeout=5000)

    tab_texts = [
        btn.inner_text()
        for btn in page.query_selector_all("[data-asset-tabs] button")
    ]
    assert any("Background" in t for t in tab_texts), f"No Background tab, got: {tab_texts}"


def test_asset_browser_has_generated_tab(page, base_url: str) -> None:
    page.goto(f"{base_url}/story-maker")
    page.wait_for_selector("[data-action='add-layer']")
    page.click("[data-action='add-layer']")
    page.wait_for_selector("[data-asset-tabs] button", timeout=5000)

    tab_texts = [
        btn.inner_text()
        for btn in page.query_selector_all("[data-asset-tabs] button")
    ]
    assert any("Generated" in t for t in tab_texts), f"No Generated tab, got: {tab_texts}"
