"""One-command editable book package pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import yaml
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from rich.console import Console
from rich.progress import track

from ..config import PROJECT_ROOT
from .affinity_export import create_affinity_package
from .character_reference import CharacterReferenceRunResult, generate_character_reference_packs
from .comfyui_engine import generate_image_comfyui
from .dgx_services import release_dgx_planner_for_images
from .idml_export import create_idml_package
from .image_engine import generate_image
from .niko_compositor import compose_niko_locked_pages, locked_illustration_path
from .niko_lock import page_fields_for_niko_lock, render_pose_library, write_lock_manifest
from .pdf_builder import build_draft_pdf, build_production_pdf
from .production_gate import evaluate_production_gate, write_production_gate_report
from .quality_checks import ImageValidationResult, parse_pixels, validate_image
from .review_package import write_review_files


NIKO_LAYER_MODE_ENV = "HACKSTER_NIKO_LAYER_MODE"

DEFAULT_NIKO_CONSISTENCY = (
    "LOCKED CHARACTER MODEL: Hackster Niko, model HN-01, is always the same small friendly learning robot, "
    "2 feet 6 inches tall, childlike proportions, softly realistic storybook materials, glossy white ceramic shell, rounded helmet-like head, "
    "smooth dark glass LED face with expressive glowing cyan-blue eyes only and no mouth, "
    "one tiny antenna with glowing blue tip, blank blue hoodie with dimensional fabric softness, one plain circular glowing cyan Core Crystal "
    "centered on the chest, compact floating magnetic backpack, rounded robot arms, rounded robot legs, "
    "blank cuffs, blank chunky sneakers, child-friendly rounded shapes, no dangling cords or straps. "
    "Niko is never an animal, never a mascot suit, never furry, never reptilian, never dragon-like, never fox-like, "
    "and never has a tail, wings, ears, snout, claws, paws, horns, scales, feathers, fur, organic limbs, or extra appendages."
)

DEFAULT_STYLE = (
    "premium dimensional children's picture book illustration, bright and warm, rounded friendly shapes, "
    "soft cinematic lighting, saturated colors, tactile painterly surfaces, whimsical cyber forest, expressive characters, "
    "no realistic weapons, no scary imagery, no text baked into image, no letters, no captions, "
    "no UI, not flat vector art, not simple sticker art, leave clean open space for editable story text."
)

DEFAULT_HIDDEN_OBJECTS = ["Golden Gear", "Tiny Bug", "Blue Crystal", "Mini Robot"]

DEFAULT_STORY_BEATS = [
    "Niko enters Cyber Forest.",
    "Password Dragon sneezes passwords everywhere.",
    "Niko comforts the dragon.",
    "Niko explains that easy passwords are weak.",
    "They build a silly strong password.",
    "Guessing Goblins try easy guesses and fail.",
    "Password Parrot almost repeats the secret.",
    "Niko explains secrets should stay secret.",
    "They build a Password Vault.",
    "The forest celebrates.",
    "A suspicious email teaser hints at Book 2: Sneaky Phish.",
]


BOOK01_PAGE_PLAN: dict[int, dict[str, Any]] = {
    1: {
        "page_type": "title_page",
        "scene_title": "Title Page",
        "story_text": "Hackster Niko and the Password Dragon",
        "illustration_direction": (
            "A polished title-page image of Hackster Niko entering Cyber Forest with warm wonder, "
            "seen from behind in a three-quarter rear view. Niko keeps the exact HN-01 robot silhouette: "
            "round helmet head, antenna, blue hoodie, compact backpack, two robot arms, two robot legs, no tail."
        ),
        "characters": ["Hackster Niko"],
        "environment": "Cyber Forest",
        "emotion": "wonder",
        "camera": "welcoming hero view",
        "hidden_objects": [],
        "text_safe_area": "Large clean title area; text will be editable in layout.",
    },
    2: {
        "page_type": "copyright",
        "scene_title": "Copyright",
        "story_text": "Copyright page. Final publisher details, ISBN, and credits will be added before print approval.",
        "illustration_direction": "Simple quiet pattern with a tiny Golden Gear and soft Cyber Forest texture, mostly open page space.",
        "characters": [],
        "environment": "",
        "emotion": "calm",
        "camera": "minimal layout",
        "hidden_objects": [],
        "text_safe_area": "Keep most of the page open for copyright text.",
    },
    3: {
        "page_type": "dedication",
        "scene_title": "Dedication",
        "story_text": "For curious kids who ask kind questions and try clever fixes.",
        "illustration_direction": "Gentle dedication-page vignette with Niko holding a glowing Golden Gear.",
        "characters": ["Hackster Niko"],
        "environment": "",
        "emotion": "kind",
        "camera": "quiet vignette",
        "hidden_objects": ["Golden Gear"],
        "text_safe_area": "Leave clean center space for dedication text.",
    },
    4: {
        "scene_title": "Niko Enters Cyber Forest",
        "story_text": '"Today is my first Junior Hackster mission," said Niko. "Every problem has a clever fix!"',
        "illustration_direction": "Niko steps onto a bright path in Cyber Forest, curious and brave.",
    },
    5: {
        "scene_title": "A Rumbling Sound",
        "story_text": 'The trees blinked with little lights. Then came a giant sneeze: "Aaa-CHOO!"',
        "illustration_direction": "Niko hears a friendly but huge sneeze echo through glowing trees.",
    },
    6: {
        "scene_title": "Passwords Everywhere",
        "story_text": '"Oh no," cried Password Dragon. "My passwords flew everywhere!"',
        "illustration_direction": "Password Dragon looks worried as harmless glowing password-shaped sparkles swirl without readable text.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    7: {
        "scene_title": "Niko Offers Help",
        "story_text": '"I can help," said Niko. "First, we stay calm. Then we think together."',
        "illustration_direction": "Niko kindly comforts Password Dragon beside a soft glowing stump.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    8: {
        "scene_title": "The Easy Password",
        "story_text": '"My favorite password is dragon," whispered the dragon. Niko blinked. "That one is easy to guess."',
        "illustration_direction": "Password Dragon whispers to Niko; show secrecy through body language, with no readable words.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    9: {
        "scene_title": "A Better Idea",
        "story_text": '"A strong password is long, silly, and hard to guess," said Niko. "Let us build one like a puzzle."',
        "illustration_direction": "Niko demonstrates puzzle pieces, gears, and crystals forming a password idea without text.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    10: {
        "scene_title": "Four Helpful Pieces",
        "story_text": '"Pick four funny things," said Niko. "A snack, a place, a color, and a surprise!"',
        "illustration_direction": "Niko and Password Dragon choose playful picture icons: snack, place, color, surprise, no labels.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    11: {
        "scene_title": "The Silly Strong Password",
        "story_text": 'Password Dragon giggled. "That is so silly!" Niko nodded. "Silly can be strong when it stays secret."',
        "illustration_direction": "Niko and Password Dragon celebrate a glowing secret recipe made of icons, not letters.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    12: {
        "scene_title": "Guessing Goblins Arrive",
        "story_text": '"Try dragon!" shouted a Guessing Goblin. "Try password!" shouted another.',
        "illustration_direction": "Small non-scary Guessing Goblins pop from bushes trying obvious guesses; no readable text.",
        "characters": ["Hackster Niko", "Password Dragon", "Guessing Goblins"],
    },
    13: {
        "scene_title": "The Guesses Fail",
        "story_text": 'The vault light stayed blue. "Nope," said Niko. "Strong passwords do not give up easily."',
        "illustration_direction": "A friendly glowing lock stays closed while goblins look puzzled, still silly and safe.",
        "characters": ["Hackster Niko", "Password Dragon", "Guessing Goblins"],
    },
    14: {
        "scene_title": "No Sharing Secrets",
        "story_text": 'Password Parrot flapped over. "Tell me the secret!" Niko said, "Passwords are private."',
        "illustration_direction": "A colorful Password Parrot asks eagerly while Niko gently raises one hand to pause.",
        "characters": ["Hackster Niko", "Password Dragon", "Password Parrot"],
    },
    15: {
        "scene_title": "Trusted Grown-Ups",
        "story_text": '"Only share passwords with a trusted grown-up when you need help," said Niko.',
        "illustration_direction": "Niko explains kindly using a safe family-help symbol made of simple shapes, no text.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    16: {
        "scene_title": "Building The Password Vault",
        "story_text": '"Let us make a Password Vault," said Niko. "It remembers secrets so you do not have to shout them."',
        "illustration_direction": "Niko assembles a friendly glowing vault from rounded gears and blue crystal panels.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    17: {
        "scene_title": "A Safe Place",
        "story_text": 'Password Dragon tucked the secret inside. Click! The vault hummed a happy little tune.',
        "illustration_direction": "Password Dragon places a glowing secret orb into the friendly vault while Niko watches.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    18: {
        "scene_title": "Teamwork Works",
        "story_text": '"I could not fix it alone," said the dragon. "That is why we use teamwork," said Niko.',
        "illustration_direction": "Niko and Password Dragon high-five beside the vault, surrounded by warm forest light.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    19: {
        "scene_title": "The Goblins Learn",
        "story_text": 'The Guessing Goblins lowered their hats. "Can we learn too?" "Of course," said Niko.',
        "illustration_direction": "The goblins become curious students while Niko points to friendly picture puzzle pieces.",
        "characters": ["Hackster Niko", "Password Dragon", "Guessing Goblins"],
    },
    20: {
        "scene_title": "Practice Time",
        "story_text": '"Long is good," said Niko. "Silly is good. Secret is best."',
        "illustration_direction": "Niko leads a cheerful practice game with icons, gears, and crystals, no letters.",
        "characters": ["Hackster Niko", "Password Dragon", "Guessing Goblins"],
    },
    21: {
        "scene_title": "The Tiny Bug",
        "story_text": 'A Tiny Bug buzzed near the vault. Niko smiled with his eyes. "Good catch. We check before we click."',
        "illustration_direction": "Niko spots a cute tiny bug near the vault and calmly inspects it with a harmless scanner.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    22: {
        "scene_title": "Crystal Check",
        "story_text": 'The Blue Crystal glowed bright. "Kindness, curiosity, and careful choices," said Niko.',
        "illustration_direction": "A Blue Crystal shines as Niko and Dragon stand in a circle of friendly forest helpers.",
        "characters": ["Hackster Niko", "Password Dragon", "Cyber Forest friends"],
    },
    23: {
        "scene_title": "The Forest Cheers",
        "story_text": '"Hooray for strong secrets!" cheered the forest friends.',
        "illustration_direction": "Cyber Forest friends celebrate with Niko and Password Dragon under glowing leaves.",
        "characters": ["Hackster Niko", "Password Dragon", "Cyber Forest friends"],
    },
    24: {
        "scene_title": "A Promise",
        "story_text": '"I will make my passwords long, silly, and secret," promised Password Dragon.',
        "illustration_direction": "Password Dragon makes a proud promise while Niko gives an encouraging thumbs-up.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    25: {
        "scene_title": "Niko's Rule",
        "story_text": 'Niko tapped his Core Crystal. "Strong passwords protect the things we care about."',
        "illustration_direction": "Niko taps the glowing Core Crystal while the vault protects friendly forest treasures.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    26: {
        "scene_title": "One More Test",
        "story_text": 'The goblins tried one last silly guess. The vault twinkled. Still safe!',
        "illustration_direction": "The goblins try a final harmless guess while the vault sparkles safely closed.",
        "characters": ["Hackster Niko", "Password Dragon", "Guessing Goblins"],
    },
    27: {
        "scene_title": "Everyone Helps",
        "story_text": '"Cyber Forest is safer when everyone helps," said Niko.',
        "illustration_direction": "Niko, Dragon, Goblins, Parrot, and forest friends tidy glowing secret sparkles together.",
        "characters": ["Hackster Niko", "Password Dragon", "Guessing Goblins", "Password Parrot", "Cyber Forest friends"],
    },
    28: {
        "scene_title": "A Thank-You Gift",
        "story_text": 'Password Dragon gave Niko a Golden Gear. "For your clever fix."',
        "illustration_direction": "Password Dragon gently gives Niko a Golden Gear as a thank-you gift.",
        "characters": ["Hackster Niko", "Password Dragon"],
    },
    29: {
        "scene_title": "Mission Complete",
        "story_text": '"Mission complete," said Niko. "And remember: every problem has a clever fix!"',
        "illustration_direction": "Niko waves goodbye on the Cyber Forest path while the vault glows safely behind.",
        "characters": ["Hackster Niko", "Password Dragon", "Cyber Forest friends"],
    },
    30: {
        "page_type": "ending",
        "scene_title": "The End",
        "story_text": "The End\nEvery problem has a clever fix!",
        "illustration_direction": "Warm celebratory ending with Niko, Password Dragon, and Cyber Forest friends.",
        "characters": ["Hackster Niko", "Password Dragon", "Cyber Forest friends"],
        "environment": "Cyber Forest",
        "emotion": "celebration",
        "camera": "wide joyful finale",
        "hidden_objects": DEFAULT_HIDDEN_OBJECTS,
        "text_safe_area": "Leave open space for The End and catchphrase as editable text.",
    },
    31: {
        "page_type": "activity",
        "scene_title": "Password Challenge",
        "story_text": "Password Challenge: With a trusted grown-up, choose four funny picture ideas. Make it long, silly, and secret.",
        "illustration_direction": "Activity-page illustration with Niko pointing to blank worksheet areas.",
        "characters": ["Hackster Niko"],
        "environment": "",
        "emotion": "encouraging",
        "camera": "activity layout",
        "hidden_objects": ["Golden Gear", "Blue Crystal"],
        "text_safe_area": "Leave large editable worksheet zones.",
    },
    32: {
        "page_type": "teaser",
        "scene_title": "Next Mission",
        "story_text": 'Then Niko saw a message blink on his tablet. "Hmm," he said. "This link looks sneaky..."',
        "illustration_direction": "Niko notices a friendly non-scary suspicious email clue on a glowing tablet; no readable screen text.",
        "characters": ["Hackster Niko"],
        "environment": "Hackster HQ",
        "emotion": "curious",
        "camera": "teaser close-up",
        "hidden_objects": ["Tiny Bug", "Mini Robot"],
        "text_safe_area": "Leave clean open area for teaser copy.",
    },
}


@dataclass(frozen=True)
class BuildOptions:
    generate_images: bool = False
    image_backend: str | None = None
    build_pdf: bool = False
    build_production_pdf: bool = False
    build_idml: bool = False
    review_only: bool = False
    force: bool = False
    limit_pages: int | None = None
    page_from: int | None = None
    page_to: int | None = None
    dry_run: bool = False
    skip_production_gate: bool = False
    force_images: bool = False
    manage_dgx_image_profile: bool = True
    generate_character_references: bool = True
    skip_character_gate: bool = False
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None


@dataclass
class BuildResult:
    book_slug: str
    book_root: Path
    page_count: int = 0
    prompts: list[Path] = field(default_factory=list)
    images: list[Path] = field(default_factory=list)
    review_files: list[Path] = field(default_factory=list)
    pdf_path: Path | None = None
    production_pdf_path: Path | None = None
    idml_path: Path | None = None
    affinity_files: list[Path] = field(default_factory=list)
    reports: list[Path] = field(default_factory=list)
    image_validations: dict[int, ImageValidationResult] = field(default_factory=dict)
    character_references: CharacterReferenceRunResult | None = None
    errors: list[str] = field(default_factory=list)


class BookBuildPipeline:
    def __init__(self, book_yaml: Path, options: BuildOptions, console: Console | None = None) -> None:
        self.book_yaml = book_yaml.expanduser()
        self.options = options
        self.console = console or Console()
        self.book_root = self.book_yaml.parent
        self.project_root = self._discover_project_root()
        self.template_env = Environment(
            loader=FileSystemLoader(PROJECT_ROOT / "hackster_studio" / "prompt_templates"),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def run(self) -> BuildResult:
        load_dotenv(self.project_root / ".env")
        book = self._load_or_create_book()
        self.book_root = self.book_yaml.parent
        result = BuildResult(book_slug=str(book["slug"]), book_root=self.book_root)
        self._emit("build_started", book_slug=result.book_slug, message="Managed book build started.")

        if self.options.dry_run:
            planned = self._planned_pages(book)
            result.page_count = len(self._limit(planned))
            self.console.print("[yellow]Dry run:[/yellow] planned files and image calls only; no files written.")
            self._print_summary(result)
            return result

        if self._requires_production_gate():
            gate = evaluate_production_gate(book_root=self.book_root, book=book)
            report_path = write_production_gate_report(self.book_root / "reports", gate)
            if not gate.pass_fail:
                self.console.print(f"[red]Production gate failed.[/red] See {report_path}")
                raise RuntimeError("Full production image generation is blocked until the pilot page passes QA.")

        self._create_folders(book)
        pages = self._load_or_create_pages(book)
        selected_pages = self._limit(pages)
        result.page_count = len(selected_pages)

        if not self.options.review_only:
            if self._character_reference_gate_enabled(book):
                self._emit("characters_started", message="Preparing reusable character reference packs.")
                result.character_references = generate_character_reference_packs(
                    book_slug=result.book_slug,
                    book=book,
                    pages=selected_pages,
                    project_root=self.project_root,
                    force=self.options.force,
                    manage_dgx_image_profile=self.options.manage_dgx_image_profile,
                    progress_callback=self.options.progress_callback,
                    console=self.console,
                )
                if not result.character_references.ready and not self.options.skip_character_gate:
                    details = "; ".join(result.character_references.errors) or "character reference QA did not pass"
                    raise RuntimeError(f"Character reference gate failed: {details}")
            self._emit("prompts_started", message="Generating page image prompts.")
            result.prompts = self._generate_prompts(book, selected_pages)
            self._emit("prompts_done", prompts=len(result.prompts), message=f"Generated {len(result.prompts)} page image prompts.")
            if self.options.generate_images:
                self._emit("images_started", pages=len(selected_pages), message=f"Starting ComfyUI image generation for {len(selected_pages)} pages.")
                result.images, result.errors = self._generate_images(book, selected_pages)
                self._emit(
                    "images_done",
                    images=len(result.images),
                    errors=len(result.errors),
                    message=f"Image generation finished with {len(result.images)} images and {len(result.errors)} errors.",
                )

        if self._niko_locked_overlay_enabled(book):
            compose_niko_locked_pages(
                pages=selected_pages,
                project_root=self.project_root,
                book_root=self.book_root,
                force=self.options.force,
            )

        validations = self._validate_images(book, selected_pages)
        result.image_validations = validations
        result.review_files = write_review_files(
            pages=self._runtime_pages(selected_pages),
            validations=validations,
            review_dir=self.book_root / "review",
            force=self.options.force,
        )
        self._emit("review_done", review_files=len(result.review_files), message=f"Wrote {len(result.review_files)} review files.")

        if self.options.build_pdf and not self.options.review_only:
            self._emit("draft_pdf_started", message="Building draft PDF.")
            result.pdf_path = build_draft_pdf(
                book=book,
                pages=self._runtime_pages(selected_pages),
                output_path=self.book_root / "pdf" / f"{book['slug']}_draft.pdf",
                force=self.options.force,
            )
            self._emit("draft_pdf_done", path=result.pdf_path.as_posix(), message="Draft PDF built.")

        if self.options.build_production_pdf and not self.options.review_only:
            self._emit("production_pdf_started", message="Building Lulu production PDF.")
            result.production_pdf_path = build_production_pdf(
                book=book,
                pages=self._runtime_pages(selected_pages),
                output_path=self.book_root / "exports" / "lulu" / f"{book['slug']}_interior_lulu_print.pdf",
                force=self.options.force,
            )
            self._emit("production_pdf_done", path=result.production_pdf_path.as_posix(), message="Lulu production PDF built.")

        if self.options.build_idml and not self.options.review_only:
            self._emit("idml_started", message="Building Affinity IDML starter package.")
            result.idml_path = create_idml_package(
                book=book,
                pages=self._runtime_pages(selected_pages),
                output_path=self.book_root / "exports" / "affinity" / f"{book['slug']}_affinity_starter.idml",
                force=self.options.force,
            )
            self._emit("idml_done", path=result.idml_path.as_posix(), message="Affinity IDML starter package built.")

        result.affinity_files = create_affinity_package(
            pages=selected_pages,
            output_dir=self.book_root / "affinity_package",
            force=self.options.force,
        )
        self._emit("affinity_done", files=len(result.affinity_files), message=f"Wrote {len(result.affinity_files)} Affinity package files.")
        result.reports = self._write_reports(book, selected_pages, validations, result)
        self._emit("reports_done", reports=len(result.reports), message=f"Wrote {len(result.reports)} production reports.")
        self._print_summary(result)
        self._emit("build_done", message="Managed book build complete.")
        return result

    def _discover_project_root(self) -> Path:
        resolved = self.book_yaml.resolve()
        if resolved.parent.parent.name == "books":
            return resolved.parent.parent.parent
        return PROJECT_ROOT

    def _load_or_create_book(self) -> dict[str, Any]:
        if self.book_yaml.exists():
            return yaml.safe_load(self.book_yaml.read_text(encoding="utf-8"))
        book = default_book_data()
        if not self.options.dry_run:
            self.book_yaml.parent.mkdir(parents=True, exist_ok=True)
            self._safe_write(self.book_yaml, yaml.safe_dump(book, sort_keys=False), binary=False)
        return book

    def _create_folders(self, book: dict[str, Any]) -> None:
        for name in ["pages", "prompts", "illustrations", "review", "affinity_package", "pdf", "reports"]:
            (self.book_root / name).mkdir(parents=True, exist_ok=True)
        if self._niko_layered_background_enabled(book):
            render_pose_library(self.project_root / "01_Characters" / "Niko" / "Poses", force=self.options.force)
            render_pose_library(self.project_root / "assets" / "layers" / "characters" / "niko", force=self.options.force)

    def _planned_pages(self, book: dict[str, Any]) -> list[dict[str, Any]]:
        return [self._page_payload(book, page_number) for page_number in range(1, int(book["page_count"]) + 1)]

    def _load_or_create_pages(self, book: dict[str, Any]) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        for page in self._planned_pages(book):
            page_path = self._page_yaml_path(int(page["page_number"]))
            if page_path.exists() and not self.options.force:
                loaded = yaml.safe_load(page_path.read_text(encoding="utf-8"))
                pages.append(loaded)
                continue
            if page_path.exists() and self.options.force:
                existing = yaml.safe_load(page_path.read_text(encoding="utf-8")) or {}
                page["approval_status"] = existing.get("approval_status", page["approval_status"])
            self._safe_write(page_path, yaml.safe_dump(page, sort_keys=False, allow_unicode=False), binary=False)
            pages.append(page)
        return pages

    def _page_payload(self, book: dict[str, Any], page_number: int) -> dict[str, Any]:
        hidden = book.get("hidden_objects") or DEFAULT_HIDDEN_OBJECTS
        prompt_path = self._rel(self.book_root / "prompts" / f"page_{page_number:03d}.md")
        illustration_path = self._rel(self.book_root / "illustrations" / f"page_{page_number:03d}.png")
        base = {
            "page_number": page_number,
            "approval_status": "needs_review",
            "illustration_path": illustration_path,
            "prompt_path": prompt_path,
        }
        if self._niko_layered_background_enabled(book):
            base |= page_fields_for_niko_lock(page_number, mode=self._niko_layer_mode(book))

        # BOOK01_PAGE_PLAN only covers book 1's 32 pages. For any other book or
        # page index, fall back to an empty plan so generic defaults apply
        # instead of raising KeyError. Book-1 pages 1-32 are unaffected (every
        # key is present in the plan).
        plan = dict(BOOK01_PAGE_PLAN.get(page_number, {}))
        page_type = str(plan.get("page_type", "story"))
        emotion_cycle = ["curious", "surprised", "caring", "confident", "playful", "relieved"]
        camera_cycle = ["wide establishing shot", "medium storybook view", "close warm character moment"]
        story_index = max(0, page_number - 4)
        fields = self._page_fields(
            page_type,
            str(plan.get("scene_title", f"Page {page_number}")),
            str(plan.get("story_text", "")),
            str(plan.get("illustration_direction", "")),
            list(plan.get("characters", ["Hackster Niko"])),
            str(plan.get("environment", "Cyber Forest")),
            str(plan.get("emotion", emotion_cycle[story_index % len(emotion_cycle)])),
            str(plan.get("camera", camera_cycle[story_index % len(camera_cycle)])),
            list(plan.get("hidden_objects", _hidden_objects_for_page(page_number, hidden) if page_type in {"story", "ending"} else [])),
            str(plan.get("text_safe_area", "Leave clean open space for editable story text inside safe margins.")),
        )
        if base.get("niko_layer_mode"):
            fields["background_direction"] = _background_direction(fields)
        return base | fields

    @staticmethod
    def _page_fields(
        page_type: str,
        scene_title: str,
        story_text: str,
        illustration_direction: str,
        characters: list[str],
        environment: str,
        emotion: str,
        camera: str,
        hidden_objects: list[str],
        text_safe_area: str,
    ) -> dict[str, Any]:
        return {
            "page_type": page_type,
            "scene_title": scene_title,
            "story_text": story_text,
            "characters": characters,
            "environment": environment,
            "emotion": emotion,
            "camera": camera,
            "illustration_direction": illustration_direction,
            "hidden_objects": hidden_objects,
            "text_safe_area": text_safe_area,
        }

    def _generate_prompts(self, book: dict[str, Any], pages: list[dict[str, Any]]) -> list[Path]:
        template = self.template_env.get_template("book_page_illustration.md.j2")
        paths: list[Path] = []
        for page in track(pages, description="Generating prompts", console=self.console):
            path = self._prompt_path(int(page["page_number"]))
            prompt_text = template.render(
                book=self._ns(book),
                page=self._ns(page),
                characters=page.get("characters", []),
                hidden_objects=page.get("hidden_objects", []),
                niko_consistency_phrase=book.get("niko_consistency", DEFAULT_NIKO_CONSISTENCY),
            )
            self._safe_write(path, prompt_text.rstrip() + "\n", binary=False)
            paths.append(path)
        return paths

    def _generate_images(self, book: dict[str, Any], pages: list[dict[str, Any]]) -> tuple[list[Path], list[str]]:
        backend = (self.options.image_backend or os.getenv("HACKSTER_IMAGE_BACKEND", "openai")).lower()
        model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
        generated: list[Path] = []
        errors: list[str] = []
        if backend == "comfyui" and self.options.manage_dgx_image_profile:
            release_dgx_planner_for_images(console=self.console)
        total_pages = len(pages)
        for index, page in enumerate(track(pages, description="Generating images", console=self.console), start=1):
            page_number = int(page["page_number"])
            image_path = self._illustration_path(page_number)
            prompt_path = self._prompt_path(page_number)
            if image_path.exists() and not self.options.force and not self.options.force_images:
                self._emit(
                    "image_page_skipped",
                    page_number=page_number,
                    page_index=index,
                    total_pages=total_pages,
                    path=image_path.as_posix(),
                    message=f"Page {page_number:03d} image already exists; skipped.",
                )
                generated.append(image_path)
                continue
            try:
                self._emit(
                    "image_page_started",
                    page_number=page_number,
                    page_index=index,
                    total_pages=total_pages,
                    path=image_path.as_posix(),
                    message=f"Generating page {page_number:03d} image in ComfyUI.",
                )
                prompt_text = prompt_path.read_text(encoding="utf-8")
                if backend == "comfyui":
                    generated.append(generate_image_comfyui(prompt_text, image_path))
                elif backend == "openai":
                    generated.append(generate_image(prompt_text, image_path, model))
                else:
                    raise ValueError(f"Unsupported image backend: {backend}. Use openai or comfyui.")
                self._emit(
                    "image_page_done",
                    page_number=page_number,
                    page_index=index,
                    total_pages=total_pages,
                    path=image_path.as_posix(),
                    message=f"Finished page {page_number:03d} image.",
                )
            except Exception as exc:
                errors.append(f"Page {page_number:03d}: {exc}")
                self.console.print(f"[red]Image generation failed for page {page_number:03d}:[/red] {exc}")
                self._emit(
                    "image_page_failed",
                    page_number=page_number,
                    page_index=index,
                    total_pages=total_pages,
                    path=image_path.as_posix(),
                    error=str(exc),
                    message=f"Image generation failed for page {page_number:03d}: {exc}",
                )
        return generated, errors

    def _emit(self, event: str, **payload: Any) -> None:
        if self.options.progress_callback:
            self.options.progress_callback(event, payload)

    def _validate_images(self, book: dict[str, Any], pages: list[dict[str, Any]]) -> dict[int, ImageValidationResult]:
        required_pixels = parse_pixels(book.get("required_pixels", "2625x2625"))
        validations: dict[int, ImageValidationResult] = {}
        for page in pages:
            page_number = int(page["page_number"])
            validations[page_number] = validate_image(page_number, self._effective_illustration_path(page_number), required_pixels)
        return validations

    def _write_reports(
        self,
        book: dict[str, Any],
        pages: list[dict[str, Any]],
        validations: dict[int, ImageValidationResult],
        result: BuildResult,
    ) -> list[Path]:
        reports_dir = self.book_root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        paths = [
            self._write_build_report(reports_dir, book, result),
            self._write_image_validation_report(reports_dir, validations),
            self._write_missing_assets_report(reports_dir, validations),
            self._write_approval_checklist(reports_dir, pages),
            self._write_niko_character_manifest(reports_dir, pages),
            write_production_gate_report(
                reports_dir,
                evaluate_production_gate(book_root=self.book_root, book=book),
            ),
        ]
        return paths

    def _write_build_report(self, reports_dir: Path, book: dict[str, Any], result: BuildResult) -> Path:
        path = reports_dir / "build_report.md"
        text = f"""# Build Report

Book: {book["title"]}

- Slug: {book["slug"]}
- Pages processed: {result.page_count}
- Generate images: {self.options.generate_images}
- Image backend: {self.options.image_backend or os.getenv("HACKSTER_IMAGE_BACKEND", "openai")}
- Build PDF: {self.options.build_pdf}
- Build production PDF: {self.options.build_production_pdf}
- Build IDML: {self.options.build_idml}
- Review only: {self.options.review_only}
- Force: {self.options.force}
- Dry run: {self.options.dry_run}
- Skip production gate: {self.options.skip_production_gate}
- Character layer mode: {book.get("character_layer_mode", "separate_layers")}
- Character reference packs: {result.character_references.character_count if result.character_references else 0}
- Draft PDF: {result.pdf_path or "not built"}
- Production PDF: {result.production_pdf_path or "not built"}
- IDML: {result.idml_path or "not built"}
- Errors: {len(result.errors)}

## Errors

{chr(10).join(f"- {error}" for error in result.errors) if result.errors else "- None"}
"""
        self._safe_write(path, text, binary=False)
        return path

    def _write_image_validation_report(
        self,
        reports_dir: Path,
        validations: dict[int, ImageValidationResult],
    ) -> Path:
        path = reports_dir / "image_validation_report.md"
        rows = [
            "| Page | Result | Exists | Size | Square | Notes |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for page_number, validation in validations.items():
            result = "PASS" if validation.pass_fail else "FAIL"
            notes = " ".join(validation.notes).replace("|", "/")
            rows.append(
                f"| {page_number:03d} | {result} | {validation.exists} | "
                f"{validation.width_px}x{validation.height_px} | {validation.is_square} | {notes} |"
            )
        self._safe_write(path, "# Image Validation Report\n\n" + "\n".join(rows) + "\n", binary=False)
        return path

    def _write_missing_assets_report(
        self,
        reports_dir: Path,
        validations: dict[int, ImageValidationResult],
    ) -> Path:
        path = reports_dir / "missing_assets_report.md"
        missing = [f"- Page {page_number:03d}: {validation.image_path}" for page_number, validation in validations.items() if not validation.exists]
        text = "# Missing Assets Report\n\n" + ("\n".join(missing) if missing else "- No missing images.") + "\n"
        self._safe_write(path, text, binary=False)
        return path

    def _write_approval_checklist(self, reports_dir: Path, pages: list[dict[str, Any]]) -> Path:
        path = reports_dir / "approval_checklist.md"
        lines = ["# Approval Checklist", ""]
        for page in pages:
            lines.append(f"- [ ] Page {int(page['page_number']):03d}: {page.get('scene_title', '')}")
        self._safe_write(path, "\n".join(lines) + "\n", binary=False)
        return path

    def _requires_production_gate(self) -> bool:
        return (
            self.options.generate_images
            and self.options.limit_pages is None
            and not self.options.review_only
            and not self.options.dry_run
            and not self.options.skip_production_gate
        )

    def _character_reference_gate_enabled(self, book: dict[str, Any] | None = None) -> bool:
        backend = (self.options.image_backend or os.getenv("HACKSTER_IMAGE_BACKEND", "openai")).lower()
        layer_mode = str((book or {}).get("character_layer_mode") or "separate_layers").strip().lower()
        return (
            self.options.generate_images
            and self.options.generate_character_references
            and backend == "comfyui"
            and layer_mode in {"separate_layers", "reference_pack", "lora_ready"}
        )

    def _niko_layer_mode(self, book: dict[str, Any] | None = None) -> str:
        env_mode = os.getenv(NIKO_LAYER_MODE_ENV)
        title = str((book or {}).get("title") or "").lower()
        if env_mode:
            configured = env_mode
        elif "hackster niko" in title:
            configured = (book or {}).get("niko_layer_mode") or "posable_layer"
        else:
            configured = "none"
        return str(configured).strip().lower()

    def _niko_layered_background_enabled(self, book: dict[str, Any] | None = None) -> bool:
        return self._niko_layer_mode(book) in {
            "posable_layer",
            "locked_overlay",
            "simple_overlay",
            "deterministic_overlay",
        }

    def _niko_locked_overlay_enabled(self, book: dict[str, Any] | None = None) -> bool:
        mode = self._niko_layer_mode(book)
        return mode in {"locked_overlay", "simple_overlay", "deterministic_overlay"}

    def _write_niko_character_manifest(self, reports_dir: Path, pages: list[dict[str, Any]]) -> Path:
        layered_modes = {"posable_layer", "locked_overlay", "simple_overlay", "deterministic_overlay"}
        if any(str(page.get("niko_layer_mode", "")).strip().lower() in layered_modes for page in pages):
            return write_lock_manifest(reports_dir / "niko_character_lock_manifest.md", book_pages=pages)

        path = reports_dir / "niko_character_lock_manifest.md"
        text = f"""# Niko Character Lock Manifest

Mode: realistic generated character

The simple deterministic overlay is disabled for production by default because it is too flat for the approved art direction.

Current production target:

- Use the realistic FLUX-rendered Niko as the visual target.
- Do not approve a full book run until the DGX has either a working FLUX reference adapter workflow or a trained Niko LoRA.
- To run the simple overlay only for engineering tests, set `{NIKO_LAYER_MODE_ENV}=locked_overlay`.
"""
        self._safe_write(path, text, binary=False)
        return path

    def _runtime_pages(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        runtime: list[dict[str, Any]] = []
        for page in pages:
            clone = dict(page)
            clone["prompt_path"] = self._prompt_path(int(page["page_number"])).as_posix()
            clone["background_illustration_path"] = self._illustration_path(int(page["page_number"])).as_posix()
            clone["locked_illustration_path"] = locked_illustration_path(self.book_root, int(page["page_number"])).as_posix()
            clone["illustration_path"] = self._effective_illustration_path(int(page["page_number"])).as_posix()
            runtime.append(clone)
        return runtime

    def _limit(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected = pages
        if self.options.page_from is not None:
            selected = [page for page in selected if int(page["page_number"]) >= self.options.page_from]
        if self.options.page_to is not None:
            selected = [page for page in selected if int(page["page_number"]) <= self.options.page_to]
        if self.options.limit_pages is None:
            return selected
        return selected[: max(0, min(32, self.options.limit_pages))]

    def _page_yaml_path(self, page_number: int) -> Path:
        return self.book_root / "pages" / f"page_{page_number:03d}.yaml"

    def _prompt_path(self, page_number: int) -> Path:
        return self.book_root / "prompts" / f"page_{page_number:03d}.md"

    def _illustration_path(self, page_number: int) -> Path:
        return self.book_root / "illustrations" / f"page_{page_number:03d}.png"

    def _effective_illustration_path(self, page_number: int) -> Path:
        locked_path = locked_illustration_path(self.book_root, page_number)
        if self._niko_locked_overlay_enabled() and locked_path.exists():
            return locked_path
        return self._illustration_path(page_number)

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.project_root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def _safe_write(self, path: Path, content: str | bytes, *, binary: bool) -> None:
        if path.exists() and not self.options.force:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        else:
            path.write_text(content if isinstance(content, str) else content.decode("utf-8"), encoding="utf-8")

    @staticmethod
    def _ns(data: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(**data)

    def _print_summary(self, result: BuildResult) -> None:
        self.console.print(f"[green]Book build finished for {result.book_slug}.[/green]")
        self.console.print(f"Pages processed: {result.page_count}")
        if result.pdf_path:
            self.console.print(f"Draft PDF: {result.pdf_path}")
        if result.production_pdf_path:
            self.console.print(f"Production PDF: {result.production_pdf_path}")
        if result.idml_path:
            self.console.print(f"IDML: {result.idml_path}")
        self.console.print(f"Review folder: {result.book_root / 'review'}")
        self.console.print(f"Affinity package: {result.book_root / 'affinity_package'}")


def default_book_data() -> dict[str, Any]:
    return {
        "title": "Hackster Niko and the Password Dragon",
        "series": "Hackster Niko",
        "slug": "book01_password_dragon",
        "trim_size": "8.5x8.5",
        "page_count": 32,
        "target_age": "5-8",
        "lesson": "strong passwords and keeping secrets safe",
        "bleed_inches": 0.125,
        "safe_margin_inches": 0.5,
        "dpi": 300,
        "full_bleed_inches": "8.75x8.75",
        "required_pixels": "2625x2625",
        "story": (
            "Niko is a friendly learning robot. Password Dragon sneezes passwords across Cyber Forest. "
            "Niko helps the dragon learn strong passwords. Sneaky Guessing Goblins try weak guesses and fail. "
            "Password Parrot almost repeats the secret. Niko teaches that passwords should stay secret. "
            "They build a Password Vault. The ending teases Book 2: Sneaky Phish."
        ),
        "niko_consistency": DEFAULT_NIKO_CONSISTENCY,
        "character_layer_mode": "separate_layers",
        "global_illustration_style": DEFAULT_STYLE,
        "hidden_objects": DEFAULT_HIDDEN_OBJECTS,
        "story_beats": DEFAULT_STORY_BEATS,
    }


def _hidden_objects_for_page(page_number: int, hidden_objects: list[str]) -> list[str]:
    if not hidden_objects:
        return []
    # Spread hidden objects across the book so "Mini Robot" does not create a second Niko on every page.
    index = (page_number - 4) % len(hidden_objects)
    return [hidden_objects[index]]


def _background_direction(page: dict[str, Any]) -> str:
    characters = [character for character in page.get("characters", []) if character != "Hackster Niko"]
    environment = page.get("environment") or "storybook setting"
    scene_title = page.get("scene_title") or "story moment"
    if not characters:
        return (
            f"Create an empty {environment} background for a quiet storybook scene. "
            "Show the setting, path, light, plants, props, and atmosphere only. No visible characters, "
            "no people, no child, no robot, no mascot, no silhouette, no antenna, no figure, "
            "no animal, no creature, no fox, no tail."
        )
    return (
        f"Create the {environment} background and include only these non-Niko characters: {', '.join(characters)}. "
        "Leave the reserved Niko overlay space empty. Do not draw Hackster Niko, any robot child, antenna, or Niko-like figure."
    )


def approve_page(book_slug: str, page_number: int) -> Path:
    page_path = PROJECT_ROOT / "books" / book_slug / "pages" / f"page_{page_number:03d}.yaml"
    if not page_path.exists():
        raise FileNotFoundError(f"Page YAML not found: {page_path}")
    page = yaml.safe_load(page_path.read_text(encoding="utf-8"))
    page["approval_status"] = "approved"
    page_path.write_text(yaml.safe_dump(page, sort_keys=False, allow_unicode=False), encoding="utf-8")
    return page_path


def status_book(book_slug: str) -> dict[str, Any]:
    root = PROJECT_ROOT / "books" / book_slug
    pages = sorted((root / "pages").glob("page_*.yaml"))
    prompts = sorted((root / "prompts").glob("page_*.md"))
    images = sorted((root / "illustrations").glob("page_*.png"))
    reviews = sorted((root / "review").glob("page_*_review.md"))
    pdf = root / "pdf" / f"{book_slug}_draft.pdf"

    approved = 0
    for page_path in pages:
        page = yaml.safe_load(page_path.read_text(encoding="utf-8"))
        if page.get("approval_status") == "approved":
            approved += 1

    return {
        "book_slug": book_slug,
        "root": root,
        "pages": len(pages),
        "prompts": len(prompts),
        "images": len(images),
        "reviews": len(reviews),
        "approved_pages": approved,
        "draft_pdf_exists": pdf.exists(),
        "draft_pdf": pdf,
    }
