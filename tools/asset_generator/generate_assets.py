#!/usr/bin/env python3
"""Generate prompt files, manifests, and review checklists from Hackster YAML specs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from jsonschema import Draft202012Validator
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except ImportError as exc:
    missing_package = exc.name or "a required package"
    print(
        f"Missing dependency: {missing_package}. "
        "Install dependencies with: python -m pip install -r tools/asset_generator/requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


ASSET_TEMPLATES: dict[str, list[str]] = {
    "character": [
        "character_turnaround_prompt.md.j2",
        "character_expressions_prompt.md.j2",
        "character_poses_prompt.md.j2",
    ],
    "environment": ["environment_prompt.md.j2"],
    "gadget": ["gadget_prompt.md.j2"],
    "book_page": ["book_page_prompt.md.j2"],
}

SCHEMA_FILES: dict[str, str] = {
    "character": "character.schema.json",
    "environment": "environment.schema.json",
    "gadget": "gadget.schema.json",
    "book_page": "book_page.schema.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Hackster Niko production prompts, manifests, and checklists."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a YAML asset spec. Relative paths are resolved from the project root or current directory.",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Optional HacksterNiko project root. Defaults to the parent project containing this script.",
    )
    return parser.parse_args()


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_project_root(project_root_arg: str | None) -> Path:
    if project_root_arg:
        return Path(project_root_arg).expanduser().resolve()
    return default_project_root()


def resolve_input_path(input_arg: str, project_root: Path) -> Path:
    input_path = Path(input_arg).expanduser()

    if input_path.is_absolute():
        return input_path

    cwd_candidate = Path.cwd() / input_path
    if cwd_candidate.exists():
        return cwd_candidate.resolve()

    return (project_root / input_path).resolve()


def relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Input YAML not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError("Input YAML must contain a top-level mapping/object.")

    return data


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Schema must be a JSON object: {path}")

    return data


def detect_asset_type(data: dict[str, Any]) -> str:
    asset_type = data.get("asset_type")
    if not isinstance(asset_type, str):
        raise ValueError("YAML must include asset_type as a string.")

    if asset_type not in ASSET_TEMPLATES:
        supported = ", ".join(sorted(ASSET_TEMPLATES))
        raise ValueError(f"Unsupported asset_type '{asset_type}'. Supported types: {supported}.")

    return asset_type


def validate_asset(data: dict[str, Any], schema: dict[str, Any]) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))

    if not errors:
        return

    messages: list[str] = []
    for error in errors:
        location = ".".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{location}: {error.message}")

    raise ValueError("Schema validation failed:\n" + "\n".join(f"- {message}" for message in messages))


def make_recommended_prefix(data: dict[str, Any]) -> str:
    asset_type = str(data["asset_type"]).replace("_", " ").title().replace(" ", "")
    name = str(data["name"]).replace(" ", "")
    version = str(data["version"]).replace(".", "p")
    return f"HN_{asset_type}_{name}_v{version}"


def template_output_name(template_name: str, slug: str, version: Any) -> str:
    prompt_kind = template_name.removesuffix("_prompt.md.j2")
    safe_version = str(version).replace(".", "p")
    return f"HN_{slug}_{prompt_kind}_v{safe_version}.prompt.md"


def render_prompts(
    data: dict[str, Any],
    asset_type: str,
    project_root: Path,
) -> list[Path]:
    generator_root = Path(__file__).resolve().parent
    templates_dir = generator_root / "templates"
    output_dir = project_root / "generated_assets" / "prompts" / asset_type / str(data["slug"])
    output_dir.mkdir(parents=True, exist_ok=True)

    environment = Environment(
        loader=FileSystemLoader(templates_dir),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    output_paths: list[Path] = []
    for template_name in ASSET_TEMPLATES[asset_type]:
        template = environment.get_template(template_name)
        rendered = template.render(**data).rstrip() + "\n"
        output_path = output_dir / template_output_name(template_name, str(data["slug"]), data["version"])
        output_path.write_text(rendered, encoding="utf-8")
        output_paths.append(output_path)

    return output_paths


def print_notes_for(asset_type: str) -> list[str]:
    common_notes = [
        "Review prompt output before pasting into an image generation tool.",
        "Do not bake story text into generated imagery.",
        "Keep important faces, hands, and story action inside print safe areas when relevant.",
    ]

    if asset_type == "book_page":
        return [
            "8.5 x 8.5 inch trim, 300 DPI intent, 0.125 inch bleed, 0.5 inch safe margin.",
            "Export final placed artwork through Affinity Publisher for Lulu first.",
            *common_notes,
        ]

    if asset_type in {"character", "gadget"}:
        return [
            "Use clean reference backgrounds for design sheets.",
            "Keep proportions consistent across generated variations.",
            *common_notes,
        ]

    return [
        "Leave usable negative space for type overlays when possible.",
        "Keep foreground, midground, and background clearly readable.",
        *common_notes,
    ]


def write_manifest(
    data: dict[str, Any],
    source_yaml: Path,
    prompt_paths: list[Path],
    project_root: Path,
) -> Path:
    slug = str(data["slug"])
    manifest_dir = project_root / "generated_assets" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{slug}.manifest.json"

    manifest = {
        "name": data["name"],
        "slug": slug,
        "asset_type": data["asset_type"],
        "version": str(data["version"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_yaml": relative_to_project(source_yaml, project_root),
        "output_prompts": [relative_to_project(path, project_root) for path in prompt_paths],
        "recommended_filename_prefix": make_recommended_prefix(data),
        "print_notes": print_notes_for(str(data["asset_type"])),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def checklist_lines(data: dict[str, Any]) -> list[str]:
    asset_type = str(data["asset_type"])
    hidden_objects = data.get("hidden_objects") or []

    lines = [
        f"# Production Checklist: {data['name']}",
        "",
        f"- Asset type: `{asset_type}`",
        f"- Slug: `{data['slug']}`",
        f"- Version: `{data['version']}`",
        "",
        "## Consistency Checks",
        "",
        "- [ ] Asset matches the approved YAML spec.",
        "- [ ] Shape language and proportions stay consistent across generated variations.",
        "- [ ] Colors match the official palette or documented local palette.",
        "- [ ] Materials are readable and repeatable for future illustration work.",
        "",
        "## Child-Friendly Checks",
        "",
        "- [ ] No weapons or weapon-like silhouettes.",
        "- [ ] No scary imagery, horror lighting, or threat poses.",
        "- [ ] Expressions and staging feel warm, clear, and emotionally safe.",
        "- [ ] Design supports kindness, curiosity, creativity, teamwork, responsibility, and courage.",
        "",
        "## Print Checks",
        "",
        "- [ ] Prompt supports high-resolution output suitable for 300 DPI print workflows.",
        "- [ ] Important story information can stay inside safe margins when used on a page.",
        "- [ ] No story text is baked into generated art.",
        "- [ ] Output can be placed cleanly into Affinity Publisher.",
        "",
        "## Brand Checks",
        "",
        "- [ ] Matches the Hackster Niko bright children's picture book style.",
        "- [ ] Uses rounded friendly shapes and soft cinematic lighting.",
        "- [ ] Preserves responsible technology tone.",
        "- [ ] Does not conflict with the Brand Bible.",
        "",
        "## Hidden Object Checks",
        "",
    ]

    if hidden_objects:
        lines.extend(f"- [ ] Hidden object planned or reviewed: {item}" for item in hidden_objects)
    else:
        lines.append("- [ ] Confirm no hidden object is required for this asset.")

    lines.extend(
        [
            "",
            "## Notes For Human Review",
            "",
            "- TODO: Record prompt edits made before image generation.",
            "- TODO: Record selected output filenames and version numbers.",
            "- TODO: Record continuity concerns before approving final art.",
            "",
        ]
    )

    return lines


def write_checklist(data: dict[str, Any], project_root: Path) -> Path:
    slug = str(data["slug"])
    checklist_dir = project_root / "generated_assets" / "checklists"
    checklist_dir.mkdir(parents=True, exist_ok=True)
    checklist_path = checklist_dir / f"{slug}.checklist.md"
    checklist_path.write_text("\n".join(checklist_lines(data)), encoding="utf-8")
    return checklist_path


def print_summary(
    console: Console,
    data: dict[str, Any],
    source_yaml: Path,
    prompt_paths: list[Path],
    manifest_path: Path,
    checklist_path: Path,
    project_root: Path,
) -> None:
    table = Table(title="Generated Hackster Asset Files")
    table.add_column("Kind", style="cyan", no_wrap=True)
    table.add_column("Path", style="white")

    table.add_row("Source", relative_to_project(source_yaml, project_root))
    for prompt_path in prompt_paths:
        table.add_row("Prompt", relative_to_project(prompt_path, project_root))
    table.add_row("Manifest", relative_to_project(manifest_path, project_root))
    table.add_row("Checklist", relative_to_project(checklist_path, project_root))

    summary = (
        f"[bold green]Generated assets for {data['name']}[/bold green]\n"
        f"Type: [bold]{data['asset_type']}[/bold] | Slug: [bold]{data['slug']}[/bold] | "
        f"Version: [bold]{data['version']}[/bold]"
    )
    console.print(Panel(summary, title="Hackster Asset Generator"))
    console.print(table)


def run() -> int:
    console = Console()
    args = parse_args()
    project_root = resolve_project_root(args.project_root)

    try:
        source_yaml = resolve_input_path(args.input, project_root)
        data = load_yaml(source_yaml)
        asset_type = detect_asset_type(data)

        schema_path = Path(__file__).resolve().parent / "schemas" / SCHEMA_FILES[asset_type]
        schema = load_json(schema_path)
        validate_asset(data, schema)

        prompt_paths = render_prompts(data, asset_type, project_root)
        manifest_path = write_manifest(data, source_yaml, prompt_paths, project_root)
        checklist_path = write_checklist(data, project_root)

        print_summary(console, data, source_yaml, prompt_paths, manifest_path, checklist_path, project_root)
        return 0
    except Exception as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())

