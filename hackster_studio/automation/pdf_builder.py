"""PDF builders for book interior review and production candidates."""

from __future__ import annotations

from pathlib import Path
from textwrap import wrap
from typing import Any

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


def _draw_wrapped_text(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width_chars: int = 42,
    leading: float = 16,
) -> None:
    pdf.setFillColor(colors.HexColor("#26313F"))
    pdf.setFont("Helvetica", 13)
    for line in wrap(text or "", width=max_width_chars)[:8]:
        pdf.drawString(x, y, line)
        y -= leading


def _draw_placeholder(pdf: canvas.Canvas, page_size: float, page_number: int, image_path: Path) -> None:
    pdf.setFillColor(colors.HexColor("#F5F8FB"))
    pdf.rect(0, 0, page_size, page_size, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#394A63"))
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawCentredString(page_size / 2, page_size / 2 + 22, f"Page {page_number:03d}")
    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(page_size / 2, page_size / 2 - 4, "Missing illustration placeholder")
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(page_size / 2, page_size / 2 - 24, image_path.as_posix())


def build_draft_pdf(
    *,
    book: dict[str, Any],
    pages: list[dict[str, Any]],
    output_path: Path,
    force: bool = False,
) -> Path:
    if output_path.exists() and not force:
        return output_path

    trim_inches = float(str(book.get("trim_size", "8.5x8.5")).split("x", 1)[0])
    page_size = trim_inches * inch
    safe_margin = float(book.get("safe_margin_inches", 0.5)) * inch
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(output_path.as_posix(), pagesize=(page_size, page_size))
    for page in pages:
        image_path = Path(page.get("illustration_path", ""))
        if image_path.exists():
            try:
                with Image.open(image_path) as image:
                    image.verify()
                pdf.drawImage(image_path.as_posix(), 0, 0, width=page_size, height=page_size, preserveAspectRatio=False)
            except Exception:
                _draw_placeholder(pdf, page_size, int(page["page_number"]), image_path)
        else:
            _draw_placeholder(pdf, page_size, int(page["page_number"]), image_path)

        story_text = str(page.get("story_text", "")).strip()
        if story_text:
            text_box_height = 1.35 * inch
            pdf.setFillColor(colors.Color(1, 1, 1, alpha=0.82))
            pdf.roundRect(
                safe_margin,
                safe_margin,
                page_size - (safe_margin * 2),
                text_box_height,
                8,
                fill=1,
                stroke=0,
            )
            _draw_wrapped_text(pdf, story_text, safe_margin + 12, safe_margin + text_box_height - 24)

        pdf.setFillColor(colors.HexColor("#697789"))
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(page_size - safe_margin, safe_margin / 2, f"{int(page['page_number']):02d}")
        pdf.showPage()

    pdf.save()
    return output_path


def build_production_pdf(
    *,
    book: dict[str, Any],
    pages: list[dict[str, Any]],
    output_path: Path,
    force: bool = False,
) -> Path:
    """Build a full-bleed print interior candidate with clean editable text overlays."""
    if output_path.exists() and not force:
        return output_path

    full_bleed_inches = float(str(book.get("full_bleed_inches", "8.75x8.75")).split("x", 1)[0])
    bleed = float(book.get("bleed_inches", 0.125)) * inch
    safe_margin = (float(book.get("safe_margin_inches", 0.5)) * inch) + bleed
    page_size = full_bleed_inches * inch
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(output_path.as_posix(), pagesize=(page_size, page_size))
    pdf.setTitle(str(book.get("title", "Hackster Niko Book")))
    pdf.setAuthor(str(book.get("series", "Hackster Niko")))

    for page in pages:
        page_number = int(page["page_number"])
        image_path = Path(page.get("illustration_path", ""))
        if image_path.exists():
            try:
                with Image.open(image_path) as image:
                    image.verify()
                pdf.drawImage(image_path.as_posix(), 0, 0, width=page_size, height=page_size, preserveAspectRatio=False)
            except Exception:
                _draw_placeholder(pdf, page_size, page_number, image_path)
        else:
            _draw_placeholder(pdf, page_size, page_number, image_path)

        _draw_production_text(pdf, page, book, page_size, safe_margin)
        pdf.showPage()

    pdf.save()
    return output_path


def _draw_production_text(
    pdf: canvas.Canvas,
    page: dict[str, Any],
    book: dict[str, Any],
    page_size: float,
    safe_margin: float,
) -> None:
    page_type = str(page.get("page_type", ""))
    text = str(page.get("story_text", "")).strip()
    if not text:
        return

    if page_type == "title_page":
        _draw_title_page_text(pdf, str(book.get("title", text)), page_size, safe_margin)
        return

    if page_type == "copyright":
        _draw_quiet_text_panel(pdf, text, page_size, safe_margin, align="left", font_size=10)
        return

    if page_type in {"dedication", "activity", "teaser"}:
        _draw_quiet_text_panel(pdf, text, page_size, safe_margin, align="center", font_size=14)
        return

    if page_type == "ending":
        _draw_story_text_panel(pdf, text, page_size, safe_margin, font_size=18)
        return

    _draw_story_text_panel(pdf, text, page_size, safe_margin, font_size=13)


def _draw_title_page_text(pdf: canvas.Canvas, title: str, page_size: float, safe_margin: float) -> None:
    lines = ["Hackster Niko", "and the", "Password Dragon"]
    center_x = page_size / 2
    top_y = page_size - 32

    _draw_shadowed_centered_text(pdf, lines[0], center_x, top_y, "Helvetica-Bold", 25)
    _draw_shadowed_centered_text(pdf, lines[1], center_x, top_y - 28, "Helvetica-Bold", 12)
    _draw_shadowed_centered_text(pdf, lines[2], center_x, top_y - 58, "Helvetica-Bold", 22)


def _draw_shadowed_centered_text(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    font_name: str,
    font_size: int,
) -> None:
    pdf.setFont(font_name, font_size)
    pdf.setFillColor(colors.HexColor("#F8FCFF"))
    for dx, dy in [(-1.2, 0), (1.2, 0), (0, -1.2), (0, 1.2)]:
        pdf.drawCentredString(x + dx, y + dy, text)
    pdf.setFillColor(colors.HexColor("#16324A"))
    pdf.drawCentredString(x, y, text)


def _draw_story_text_panel(
    pdf: canvas.Canvas,
    text: str,
    page_size: float,
    safe_margin: float,
    *,
    font_size: int,
) -> None:
    box_width = page_size - (safe_margin * 2)
    box_height = 1.55 * inch
    x = safe_margin
    y = safe_margin
    _draw_text_panel_background(pdf, x, y, box_width, box_height)

    pdf.setFillColor(colors.HexColor("#26313F"))
    lines = _wrapped_lines(text, width=54 if font_size <= 13 else 38)
    font_size = _fit_font_size(lines, starting_size=font_size, max_lines=6)
    pdf.setFont("Helvetica", font_size)
    leading = font_size + 4
    text_y = y + box_height - 26
    for line in lines[:6]:
        pdf.drawString(x + 16, text_y, line)
        text_y -= leading


def _draw_quiet_text_panel(
    pdf: canvas.Canvas,
    text: str,
    page_size: float,
    safe_margin: float,
    *,
    align: str,
    font_size: int,
) -> None:
    box_width = page_size - (safe_margin * 2)
    box_height = 1.6 * inch
    x = safe_margin
    y = safe_margin
    _draw_text_panel_background(pdf, x, y, box_width, box_height)

    pdf.setFillColor(colors.HexColor("#26313F"))
    lines = _wrapped_lines(text, width=48)
    font_size = _fit_font_size(lines, starting_size=font_size, max_lines=6)
    pdf.setFont("Helvetica", font_size)
    leading = font_size + 5
    text_y = y + box_height - 30
    for line in lines[:6]:
        if align == "center":
            pdf.drawCentredString(page_size / 2, text_y, line)
        else:
            pdf.drawString(x + 16, text_y, line)
        text_y -= leading


def _draw_text_panel_background(pdf: canvas.Canvas, x: float, y: float, width: float, height: float) -> None:
    pdf.setFillColor(colors.HexColor("#F8FCFF"))
    pdf.roundRect(x, y, width, height, 10, fill=1, stroke=0)
    pdf.setStrokeColor(colors.HexColor("#DDEAF5"))
    pdf.setLineWidth(0.8)
    pdf.roundRect(x, y, width, height, 10, fill=0, stroke=1)


def _wrapped_lines(text: str, *, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        lines.extend(wrap(paragraph, width=width))
    return lines


def _fit_font_size(lines: list[str], *, starting_size: int, max_lines: int) -> int:
    if len(lines) <= max_lines:
        return starting_size
    overflow = len(lines) - max_lines
    return max(9, starting_size - overflow)
