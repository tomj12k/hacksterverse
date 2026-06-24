"""Typer CLI for Hackster Studio."""

from __future__ import annotations

from pathlib import Path
import subprocess

import typer
import uvicorn
import yaml
from rich.console import Console
from rich.table import Table
from sqlmodel import Session, func, select

from .automation.build_book import build_book
from .automation.movie_pipeline import MovieBuildOptions, build_movie_package
from .automation.niko_compositor import compose_niko_locked_pages
from .automation.niko_lock import render_pose_library
from .automation.pipeline import BuildOptions, approve_page as approve_book_page, status_book as get_book_status
from .automation.production_gate import evaluate_production_gate, write_production_gate_report
from .database import engine, init_db as create_tables
from .models import Book, Character, Environment, Gadget, Page, PrintReport, Project, Prompt
from .services.books import plan_book, upsert_password_dragon_book, upsert_project
from .services.characters import upsert_hackster_niko
from .services.environments import upsert_cyber_forest
from .services.exports import export_page_specs_yaml, relative_path
from .services.gadgets import upsert_code_scanner
from .services.print_validator import validate_image_for_print
from .services.prompts import generate_prompts_for_book


app = typer.Typer(help="Hackster Studio local publishing tools.")
console = Console()


def _count(session: Session, model: type) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one())


@app.command("init-db")
def init_db_command() -> None:
    """Create the SQLite database and tables."""
    create_tables()
    console.print("[green]Database initialized.[/green]")


@app.command()
def seed() -> None:
    """Seed the Hackster Niko starter project."""
    create_tables()
    with Session(engine) as session:
        upsert_project(session)
        upsert_hackster_niko(session)
        upsert_cyber_forest(session)
        upsert_code_scanner(session)
        upsert_password_dragon_book(session)
    console.print("[green]Seed data ready.[/green]")


@app.command()
def run() -> None:
    """Start the local FastAPI development server."""
    uvicorn.run("hackster_studio.main:app", host="127.0.0.1", port=8000, reload=True)


@app.command("plan-book")
def plan_book_command(book_slug: str) -> None:
    """Generate or update a 32-page plan for a book."""
    create_tables()
    with Session(engine) as session:
        pages = plan_book(session, book_slug)
    console.print(f"[green]Planned {len(pages)} pages for {book_slug}.[/green]")


@app.command("generate-prompts")
def generate_prompts_command(book_slug: str) -> None:
    """Generate Markdown prompts for all pages in a book."""
    create_tables()
    with Session(engine) as session:
        prompts = generate_prompts_for_book(session, book_slug)
    console.print(f"[green]Generated {len(prompts)} page prompts for {book_slug}.[/green]")


@app.command("export-yaml")
def export_yaml_command(book_slug: str) -> None:
    """Export book page specs as YAML files."""
    create_tables()
    with Session(engine) as session:
        output_paths = export_page_specs_yaml(session, book_slug)
    console.print(f"[green]Exported {len(output_paths)} YAML page specs.[/green]")
    console.print(f"Directory: data/generated/page_specs/{book_slug}/")


@app.command("check-consistency")
def check_consistency_command(book_slug: str) -> None:
    """Report drift between a book's DB rows, YAML, scenes, and artifacts."""
    from .services.consistency import book_consistency_report

    create_tables()
    with Session(engine) as session:
        report = book_consistency_report(session, book_slug)
    table = Table(title=f"Consistency: {book_slug}")
    table.add_column("Store")
    table.add_column("Count", justify="right")
    for key, value in report["counts"].items():
        table.add_row(key, str(value))
    console.print(table)
    if report["consistent"]:
        console.print("[green]All stores are consistent.[/green]")
    else:
        for message in report["drift"]:
            console.print(f"[yellow]drift:[/yellow] {message}")


@app.command("print-check")
def print_check_command(path: str) -> None:
    """Validate an image file for Lulu full-bleed print readiness."""
    create_tables()
    with Session(engine) as session:
        report = validate_image_for_print(session, path)

    result = "PASS" if report.pass_fail else "FAIL"
    color = "green" if report.pass_fail else "red"
    console.print(f"[{color}]{result}[/{color}] {report.file_path}")
    console.print(
        f"{report.width_px} x {report.height_px}px, "
        f"DPI {report.dpi_x:g} x {report.dpi_y:g}; required "
        f"{report.required_width_px} x {report.required_height_px}px at 300 DPI."
    )
    console.print(report.notes)


@app.command()
def status() -> None:
    """Show project counts and missing production work."""
    create_tables()
    with Session(engine) as session:
        table = Table(title="Hackster Studio Status")
        table.add_column("Area", style="cyan")
        table.add_column("Count", justify="right")
        for name, model in [
            ("Projects", Project),
            ("Characters", Character),
            ("Environments", Environment),
            ("Gadgets", Gadget),
            ("Books", Book),
            ("Pages", Page),
            ("Prompts", Prompt),
            ("Print Reports", PrintReport),
        ]:
            table.add_row(name, str(_count(session, model)))

        missing_illustrations = session.exec(
            select(func.count()).select_from(Page).where(Page.illustration_path == "")
        ).one()
        missing_prompts = session.exec(
            select(func.count()).select_from(Page).where(Page.prompt_path == "")
        ).one()

    console.print(table)
    console.print(f"Missing page prompts: {missing_prompts}")
    console.print(f"Missing page illustrations: {missing_illustrations}")
    console.print("Generated page specs: data/generated/page_specs/")
    console.print("Generated prompts: data/generated/prompts/")


@app.command("build-book")
def build_book_command(
    book_yaml: str,
    generate_images: bool = typer.Option(False, "--generate-images/--no-images", help="Generate missing page art using the selected backend."),
    image_backend: str | None = typer.Option(None, "--image-backend", help="Image backend to use with --generate-images: openai or comfyui. Defaults to HACKSTER_IMAGE_BACKEND or openai."),
    build_pdf: bool = typer.Option(False, "--build-pdf/--no-pdf", help="Build a draft PDF interior."),
    production_pdf: bool = typer.Option(False, "--production-pdf/--no-production-pdf", help="Build a full-bleed production interior PDF candidate."),
    idml: bool = typer.Option(False, "--idml/--no-idml", help="Build an IDML starter package for Affinity Publisher import."),
    review_only: bool = typer.Option(False, "--review-only", help="Only rebuild review/checklist files from current assets."),
    force: bool = typer.Option(False, "--force", help="Overwrite generated files that already exist."),
    limit_pages: int | None = typer.Option(None, "--limit-pages", min=1, max=32, help="Only process the first N pages for testing."),
    page_from: int | None = typer.Option(None, "--page-from", min=1, max=32, help="Process pages starting at this page number."),
    page_to: int | None = typer.Option(None, "--page-to", min=1, max=32, help="Process pages through this page number."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan the build without writing files or calling image generation."),
    skip_production_gate: bool = typer.Option(False, "--skip-production-gate", help="Allow a full image run without an approved pilot page. Use only for deliberate experiments."),
) -> None:
    """Build an editable local book package from book.yaml."""
    options = BuildOptions(
        generate_images=generate_images,
        image_backend=image_backend,
        build_pdf=build_pdf,
        build_production_pdf=production_pdf,
        build_idml=idml,
        review_only=review_only,
        force=force,
        limit_pages=limit_pages,
        page_from=page_from,
        page_to=page_to,
        dry_run=dry_run,
        skip_production_gate=skip_production_gate,
    )
    try:
        build_book(Path(book_yaml), options, console=console)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@app.command("build-movie-package")
def build_movie_package_command(
    movie_yaml: str,
    force: bool = typer.Option(False, "--force", help="Overwrite generated movie package files."),
    limit_shots: int | None = typer.Option(None, "--limit-shots", min=1, help="Only process the first N shots for testing."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan the package without writing files."),
) -> None:
    """Build a shot-based movie production package from movie.yaml."""
    options = MovieBuildOptions(force=force, limit_shots=limit_shots, dry_run=dry_run)
    try:
        build_movie_package(Path(movie_yaml), options, console=console)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@app.command("build-niko-lock")
def build_niko_lock_command(
    output_dir: str = typer.Option("01_Characters/Niko/Poses", "--output-dir", help="Directory for locked Niko transparent PNG pose assets."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing pose assets."),
) -> None:
    """Render deterministic locked Niko pose assets."""
    paths = render_pose_library(Path(output_dir), force=force)
    console.print(f"[green]Rendered {len(paths)} locked Niko pose assets.[/green]")
    for path in paths:
        console.print(str(path))


@app.command("compose-niko-lock")
def compose_niko_lock_command(
    book_yaml: str,
    force: bool = typer.Option(False, "--force", help="Overwrite existing locked-composite page images."),
) -> None:
    """Composite locked Niko pose assets over existing generated backgrounds."""
    book_path = Path(book_yaml).expanduser()
    if not book_path.exists():
        console.print(f"[red]Book YAML not found:[/red] {book_path}")
        raise typer.Exit(1)
    pages_dir = book_path.parent / "pages"
    pages = [yaml.safe_load(path.read_text(encoding="utf-8")) for path in sorted(pages_dir.glob("page_*.yaml"))]
    composed = compose_niko_locked_pages(
        pages=pages,
        project_root=book_path.parent.parent.parent,
        book_root=book_path.parent,
        force=force,
    )
    console.print(f"[green]Composited {len(composed)} locked Niko page images.[/green]")
    for page_number, path in sorted(composed.items()):
        console.print(f"{page_number:03d}: {path}")


@app.command("open-affinity")
def open_affinity_command(
    book_yaml: str,
    handoff_format: str = typer.Option("pdf", "--format", help="Affinity handoff format to open: pdf or idml."),
) -> None:
    """Open the current book handoff in the installed Affinity app."""
    book_path = Path(book_yaml).expanduser()
    book_root = book_path.parent
    if not book_path.exists():
        console.print(f"[red]Book YAML not found:[/red] {book_path}")
        raise typer.Exit(1)

    if handoff_format == "pdf":
        candidates = sorted(
            (book_root / "exports" / "lulu").glob("*_interior_lulu_print*.pdf"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        note = "PDF imports as 32 Affinity pages with editable text layers."
    elif handoff_format == "idml":
        candidates = sorted(
            (book_root / "exports" / "affinity").glob("*.idml"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        note = "IDML is experimental; Affinity 3.2.2 on this Mac does not declare .idml as an openable type."
    else:
        console.print("[red]Unsupported format.[/red] Use pdf or idml.")
        raise typer.Exit(1)

    if not candidates:
        console.print(f"[red]No {handoff_format.upper()} handoff export found.[/red]")
        raise typer.Exit(1)

    target = candidates[0]
    console.print(f"[green]Opening in Affinity:[/green] {target}")
    console.print(note)
    subprocess.run(["open", "-a", "/Applications/Affinity.app", str(target)], check=True)


@app.command("qa-gate")
def qa_gate_command(
    book_yaml: str,
    page_number: int = typer.Option(1, "--page", min=1, max=32, help="Pilot page number to evaluate."),
) -> None:
    """Check whether the approved pilot page unlocks full production generation."""
    book_path = Path(book_yaml).expanduser()
    if not book_path.exists():
        console.print(f"[red]Book YAML not found:[/red] {book_path}")
        raise typer.Exit(1)

    book = yaml.safe_load(book_path.read_text(encoding="utf-8")) or {}
    result = evaluate_production_gate(book_root=book_path.parent, book=book, page_number=page_number)
    report_path = write_production_gate_report(book_path.parent / "reports", result)
    status = "PASS" if result.pass_fail else "FAIL"
    color = "green" if result.pass_fail else "red"

    console.print(f"[{color}]Production gate {status}[/{color}]")
    console.print(f"Pilot page: {page_number:03d}")
    console.print(f"Approved: {result.approved}")
    console.print(f"Image: {result.image_validation.width_px}x{result.image_validation.height_px}")
    console.print(f"Report: {report_path}")
    if not result.pass_fail:
        for note in result.notes:
            console.print(f"- {note}")
        raise typer.Exit(1)


@app.command("approve-page")
def approve_page_command(book_slug: str, page_number: int) -> None:
    """Mark a page YAML as approved after human review."""
    page_path = approve_book_page(book_slug, page_number)
    console.print(f"[green]Approved page {page_number:03d}.[/green] {page_path}")


@app.command("status-book")
def status_book_command(book_slug: str) -> None:
    """Show package status for a generated book."""
    status_data = get_book_status(book_slug)
    table = Table(title=f"Book Status: {book_slug}")
    table.add_column("Area", style="cyan")
    table.add_column("Value", justify="right")
    for key in ["pages", "prompts", "images", "reviews", "approved_pages", "draft_pdf_exists"]:
        table.add_row(key.replace("_", " ").title(), str(status_data[key]))
    console.print(table)
    console.print(f"Root: {status_data['root']}")
    console.print(f"Draft PDF: {status_data['draft_pdf']}")


if __name__ == "__main__":
    app()
