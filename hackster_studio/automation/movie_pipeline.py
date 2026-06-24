"""Shot-based movie package pipeline for Hackster Niko productions."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader
from rich.console import Console
from rich.progress import track

from ..config import PROJECT_ROOT
from .pipeline import DEFAULT_NIKO_CONSISTENCY, DEFAULT_STYLE


DEFAULT_MOVIE_MODELS = {
    "script_llm": "Qwen3.6 or Llama 4",
    "keyframes": "FLUX.1-dev or SDXL illustration checkpoint",
    "video": "Wan 2.2 I2V/TI2V",
    "dialogue": "Chatterbox TTS or CosyVoice",
    "lip_sync": "LatentSync, with MuseTalk for fast talking-head tests",
    "music": "ACE-Step 1.5",
    "sfx": "AudioLDM2, with Stable Audio Open as a gated optional upgrade",
    "assembly": "DaVinci Resolve, Premiere, or ffmpeg",
}


DEFAULT_MOVIE_SHOTS: list[dict[str, Any]] = [
    {
        "shot_id": "SH010",
        "source_page": 4,
        "scene_title": "Cyber Forest Opens",
        "duration_seconds": 5,
        "shot_type": "establishing",
        "camera": "slow push-in from a wide view",
        "motion": "glowing leaves pulse softly while tiny light paths wake up",
        "description": "Cyber Forest comes alive as Niko enters on a bright safe path.",
        "characters": ["Hackster Niko"],
        "dialogue": [],
        "narration": "In Cyber Forest, a first mission was about to begin.",
        "sfx": ["soft digital chimes", "gentle forest sparkle"],
        "music": "warm curious opening theme, light marimba and soft synth",
        "continuity_notes": "Niko is small in frame; keep the silhouette readable and friendly.",
    },
    {
        "shot_id": "SH020",
        "source_page": 4,
        "scene_title": "Niko's Mission",
        "duration_seconds": 6,
        "shot_type": "medium character",
        "camera": "medium front three-quarter view at child height",
        "motion": "Niko steps forward and his cyan eyes brighten with confidence",
        "description": "Niko pauses on the path, ready for his first Junior Hackster mission.",
        "characters": ["Hackster Niko"],
        "dialogue": [
            {"speaker": "Niko", "text": "Today is my first Junior Hackster mission."},
            {"speaker": "Niko", "text": "Every problem has a clever fix!"},
        ],
        "narration": "",
        "sfx": ["small servo step", "friendly core crystal glow"],
        "music": "opening theme continues with a hopeful lift",
        "continuity_notes": "No mouth on Niko; show emotion through eyes, antenna glow, and body language.",
    },
    {
        "shot_id": "SH030",
        "source_page": 5,
        "scene_title": "The Giant Sneeze",
        "duration_seconds": 5,
        "shot_type": "reaction",
        "camera": "quick gentle pan from blinking trees to Niko",
        "motion": "tree lights flicker, leaves wiggle, Niko looks up surprised",
        "description": "A huge friendly sneeze echoes through the glowing trees.",
        "characters": ["Hackster Niko"],
        "dialogue": [],
        "narration": "Then came a giant sneeze.",
        "sfx": ["distant friendly sneeze", "fluttering leaves"],
        "music": "brief playful pause, then a curious bounce",
        "continuity_notes": "Keep the sneeze comic, never frightening.",
    },
    {
        "shot_id": "SH040",
        "source_page": 6,
        "scene_title": "Password Dragon Appears",
        "duration_seconds": 7,
        "shot_type": "two character reveal",
        "camera": "wide-to-medium reveal with Niko in foreground",
        "motion": "harmless glowing secret-orbs swirl around the worried dragon",
        "description": "Password Dragon sits among floating password sparkles, worried but gentle.",
        "characters": ["Hackster Niko", "Password Dragon"],
        "dialogue": [{"speaker": "Password Dragon", "text": "Oh no. My passwords flew everywhere!"}],
        "narration": "",
        "sfx": ["soft dragon sniffle", "floating sparkle whooshes"],
        "music": "tender comic trouble motif",
        "continuity_notes": "No readable passwords, letters, numbers, or symbols in the image.",
    },
    {
        "shot_id": "SH050",
        "source_page": 7,
        "scene_title": "Stay Calm",
        "duration_seconds": 6,
        "shot_type": "comfort beat",
        "camera": "warm medium close-up",
        "motion": "Niko raises one hand gently; Password Dragon relaxes a little",
        "description": "Niko comforts Password Dragon beside a glowing stump.",
        "characters": ["Hackster Niko", "Password Dragon"],
        "dialogue": [
            {"speaker": "Niko", "text": "I can help."},
            {"speaker": "Niko", "text": "First, we stay calm. Then we think together."},
        ],
        "narration": "",
        "sfx": ["soft calming shimmer"],
        "music": "warm reassurance, simple bell notes",
        "continuity_notes": "Body language should be gentle and emotionally safe.",
    },
    {
        "shot_id": "SH060",
        "source_page": 10,
        "scene_title": "Four Funny Pieces",
        "duration_seconds": 7,
        "shot_type": "explanation",
        "camera": "over-the-shoulder view of picture icons",
        "motion": "four picture icons float into place like puzzle pieces",
        "description": "Niko shows four funny picture ideas for building a long password.",
        "characters": ["Hackster Niko", "Password Dragon"],
        "dialogue": [{"speaker": "Niko", "text": "Pick four funny things: a snack, a place, a color, and a surprise."}],
        "narration": "",
        "sfx": ["picture-card pops", "gentle puzzle clicks"],
        "music": "light learning rhythm",
        "continuity_notes": "Use pictures only; do not render labels or readable text.",
    },
    {
        "shot_id": "SH070",
        "source_page": 12,
        "scene_title": "Guessing Goblins Try",
        "duration_seconds": 6,
        "shot_type": "comic obstacle",
        "camera": "low playful angle on bushes and vault light",
        "motion": "small silly goblins pop from bushes while the vault remains blue",
        "description": "Guessing Goblins try obvious guesses and fail against the friendly vault.",
        "characters": ["Hackster Niko", "Password Dragon", "Guessing Goblins"],
        "dialogue": [
            {"speaker": "Guessing Goblin", "text": "Try dragon!"},
            {"speaker": "Guessing Goblin", "text": "Try password!"},
            {"speaker": "Niko", "text": "Nope. Strong passwords do not give up easily."},
        ],
        "narration": "",
        "sfx": ["tiny bush pops", "safe vault hum"],
        "music": "playful comic pizzicato",
        "continuity_notes": "Goblins are cute, non-threatening, and curious.",
    },
    {
        "shot_id": "SH080",
        "source_page": 14,
        "scene_title": "Password Parrot",
        "duration_seconds": 6,
        "shot_type": "privacy lesson",
        "camera": "medium shot with parrot entering from above",
        "motion": "Password Parrot flutters in; Niko gently pauses the conversation",
        "description": "Password Parrot asks for the secret and Niko explains privacy.",
        "characters": ["Hackster Niko", "Password Dragon", "Password Parrot"],
        "dialogue": [
            {"speaker": "Password Parrot", "text": "Tell me the secret!"},
            {"speaker": "Niko", "text": "Passwords are private."},
        ],
        "narration": "",
        "sfx": ["soft wing flutter", "gentle pause chime"],
        "music": "kind teaching motif",
        "continuity_notes": "Do not shame the parrot; it should look eager, not sneaky.",
    },
    {
        "shot_id": "SH090",
        "source_page": 16,
        "scene_title": "Build The Vault",
        "duration_seconds": 8,
        "shot_type": "making montage",
        "camera": "three quick montage beats in one continuous shot",
        "motion": "rounded gears, blue crystal panels, and soft locks assemble into a friendly vault",
        "description": "Niko and Password Dragon build a Password Vault together.",
        "characters": ["Hackster Niko", "Password Dragon"],
        "dialogue": [{"speaker": "Niko", "text": "It remembers secrets so you do not have to shout them."}],
        "narration": "",
        "sfx": ["rounded gear clicks", "blue crystal glow", "happy vault hum"],
        "music": "upbeat teamwork montage",
        "continuity_notes": "The vault should feel like a helpful tool, not a scary lockup.",
    },
    {
        "shot_id": "SH100",
        "source_page": 18,
        "scene_title": "Teamwork Works",
        "duration_seconds": 6,
        "shot_type": "emotional payoff",
        "camera": "medium two-shot",
        "motion": "Niko and Password Dragon high-five beside the glowing vault",
        "description": "The friends celebrate that teamwork solved the problem.",
        "characters": ["Hackster Niko", "Password Dragon"],
        "dialogue": [
            {"speaker": "Password Dragon", "text": "I could not fix it alone."},
            {"speaker": "Niko", "text": "That is why we use teamwork."},
        ],
        "narration": "",
        "sfx": ["soft high-five tap", "happy vault tune"],
        "music": "warm payoff phrase",
        "continuity_notes": "Keep Niko mouthless; high-five works through pose and eye expression.",
    },
    {
        "shot_id": "SH110",
        "source_page": 23,
        "scene_title": "Forest Cheers",
        "duration_seconds": 7,
        "shot_type": "celebration",
        "camera": "wide joyful finale with gentle crane up",
        "motion": "forest friends cheer under glowing leaves; hidden objects sparkle subtly",
        "description": "Cyber Forest celebrates strong secrets and careful choices.",
        "characters": ["Hackster Niko", "Password Dragon", "Cyber Forest friends"],
        "dialogue": [{"speaker": "Forest Friends", "text": "Hooray for strong secrets!"}],
        "narration": "",
        "sfx": ["soft cheering", "sparkling leaves"],
        "music": "full bright theme reprise",
        "continuity_notes": "Celebration stays readable and uncluttered.",
    },
    {
        "shot_id": "SH120",
        "source_page": 32,
        "scene_title": "Next Mission Teaser",
        "duration_seconds": 6,
        "shot_type": "tag",
        "camera": "close-up on Niko and glowing tablet",
        "motion": "Niko notices a blinking tablet message and tilts his head curiously",
        "description": "A friendly suspicious-message clue teases the next mission.",
        "characters": ["Hackster Niko"],
        "dialogue": [{"speaker": "Niko", "text": "Hmm. This link looks sneaky..."}],
        "narration": "",
        "sfx": ["tablet blink", "curious tiny beep"],
        "music": "small mystery button, still safe and playful",
        "continuity_notes": "No readable screen text or real brand logos.",
    },
]


@dataclass(frozen=True)
class MovieBuildOptions:
    force: bool = False
    limit_shots: int | None = None
    dry_run: bool = False


@dataclass
class MovieBuildResult:
    movie_slug: str
    movie_root: Path
    shot_count: int = 0
    shot_files: list[Path] = field(default_factory=list)
    prompt_files: list[Path] = field(default_factory=list)
    audio_files: list[Path] = field(default_factory=list)
    edit_files: list[Path] = field(default_factory=list)
    review_files: list[Path] = field(default_factory=list)
    reports: list[Path] = field(default_factory=list)


class MovieBuildPipeline:
    """Create a repeatable movie production package from a movie YAML file."""

    def __init__(self, movie_yaml: Path, options: MovieBuildOptions, console: Console | None = None) -> None:
        self.movie_yaml = movie_yaml.expanduser()
        self.options = options
        self.console = console or Console()
        self.movie_root = self.movie_yaml.parent
        self.project_root = self._discover_project_root()
        self.template_env = Environment(
            loader=FileSystemLoader(PROJECT_ROOT / "hackster_studio" / "prompt_templates"),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def run(self) -> MovieBuildResult:
        movie = self._load_or_create_movie()
        self.movie_root = self.movie_yaml.parent
        shots = self._limit(self._planned_shots(movie))
        result = MovieBuildResult(movie_slug=str(movie["slug"]), movie_root=self.movie_root, shot_count=len(shots))

        if self.options.dry_run:
            self.console.print("[yellow]Dry run:[/yellow] planned movie package only; no files written.")
            self._print_summary(result)
            return result

        self._create_folders()
        result.shot_files = self._write_shots(shots)
        result.prompt_files = self._write_prompts(movie, shots)
        result.audio_files = self._write_audio_cues(movie, shots)
        result.edit_files = self._write_edit_package(movie, shots)
        result.review_files = self._write_review_files(shots)
        result.reports = [self._write_build_report(movie, result), self._write_model_handoff(movie)]
        self._print_summary(result)
        return result

    def _discover_project_root(self) -> Path:
        resolved = self.movie_yaml.resolve()
        if resolved.parent.parent.name == "movies":
            return resolved.parent.parent.parent
        return PROJECT_ROOT

    def _load_or_create_movie(self) -> dict[str, Any]:
        if self.movie_yaml.exists():
            return yaml.safe_load(self.movie_yaml.read_text(encoding="utf-8"))
        movie = default_movie_data()
        if not self.options.dry_run:
            self.movie_yaml.parent.mkdir(parents=True, exist_ok=True)
            self._safe_write(self.movie_yaml, yaml.safe_dump(movie, sort_keys=False, allow_unicode=False))
        return movie

    def _planned_shots(self, movie: dict[str, Any]) -> list[dict[str, Any]]:
        shots = [self._shot_payload(movie, shot) for shot in movie.get("shots", DEFAULT_MOVIE_SHOTS)]
        return shots

    def _shot_payload(self, movie: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
        shot_id = str(shot["shot_id"])
        outputs = {
            "keyframe_path": self._rel(self.movie_root / "renders" / "keyframes" / f"{shot_id}_keyframe.png"),
            "video_raw_path": self._rel(self.movie_root / "renders" / "video_raw" / f"{shot_id}_raw.mp4"),
            "video_lipsynced_path": self._rel(self.movie_root / "renders" / "video_lipsynced" / f"{shot_id}_lipsync.mp4"),
            "dialogue_audio_path": self._rel(self.movie_root / "audio" / "dialogue" / f"{shot_id}_dialogue.wav"),
            "mix_audio_path": self._rel(self.movie_root / "audio" / "mixes" / f"{shot_id}_mix.wav"),
        }
        return {
            "approval_status": "needs_review",
            "fps": movie.get("fps", 24),
            "resolution": movie.get("resolution", "1920x1080"),
            "aspect_ratio": movie.get("aspect_ratio", "16:9"),
            **shot,
            **outputs,
        }

    def _create_folders(self) -> None:
        for folder in [
            "shots",
            "prompts/keyframes",
            "prompts/video",
            "audio/dialogue",
            "audio/sfx",
            "audio/music",
            "audio/mixes",
            "renders/keyframes",
            "renders/video_raw",
            "renders/video_lipsynced",
            "renders/final",
            "edit",
            "review",
            "reports",
            "references",
        ]:
            (self.movie_root / folder).mkdir(parents=True, exist_ok=True)

    def _write_shots(self, shots: list[dict[str, Any]]) -> list[Path]:
        paths: list[Path] = []
        for shot in shots:
            path = self.movie_root / "shots" / f"{shot['shot_id']}.yaml"
            self._safe_write(path, yaml.safe_dump(shot, sort_keys=False, allow_unicode=False))
            paths.append(path)
        return paths

    def _write_prompts(self, movie: dict[str, Any], shots: list[dict[str, Any]]) -> list[Path]:
        keyframe_template = self.template_env.get_template("movie_keyframe.md.j2")
        video_template = self.template_env.get_template("movie_shot_video.md.j2")
        paths: list[Path] = []
        for shot in track(shots, description="Writing movie prompts", console=self.console):
            data = {
                "movie": self._ns(movie),
                "shot": self._ns(shot),
                "niko_consistency_phrase": movie.get("niko_consistency", DEFAULT_NIKO_CONSISTENCY),
                "global_style": movie.get("global_visual_style", DEFAULT_STYLE),
            }
            keyframe_path = self.movie_root / "prompts" / "keyframes" / f"{shot['shot_id']}_keyframe.md"
            video_path = self.movie_root / "prompts" / "video" / f"{shot['shot_id']}_video.md"
            self._safe_write(keyframe_path, keyframe_template.render(**data).rstrip() + "\n")
            self._safe_write(video_path, video_template.render(**data).rstrip() + "\n")
            paths.extend([keyframe_path, video_path])
        return paths

    def _write_audio_cues(self, movie: dict[str, Any], shots: list[dict[str, Any]]) -> list[Path]:
        paths: list[Path] = []
        for shot in shots:
            shot_id = str(shot["shot_id"])
            dialogue_path = self.movie_root / "audio" / "dialogue" / f"{shot_id}_dialogue.txt"
            sfx_path = self.movie_root / "audio" / "sfx" / f"{shot_id}_sfx.md"
            dialogue_lines = _dialogue_lines(shot)
            dialogue_text = "\n".join(dialogue_lines) if dialogue_lines else "# No dialogue for this shot."
            self._safe_write(dialogue_path, dialogue_text.rstrip() + "\n")
            self._safe_write(
                sfx_path,
                f"# {shot_id} SFX Cues\n\n"
                + "\n".join(f"- {cue}" for cue in shot.get("sfx", []))
                + "\n\n"
                + f"Music cue: {shot.get('music', movie.get('music_direction', ''))}\n",
            )
            paths.extend([dialogue_path, sfx_path])

        music_path = self.movie_root / "audio" / "music" / "music_brief.md"
        self._safe_write(
            music_path,
            f"""# Music Brief

Movie: {movie["title"]}

Target: {movie.get("runtime_seconds", 90)} seconds

Direction: {movie.get("music_direction", "Warm, playful, child-safe adventure score.")}

Model handoff: ACE-Step 1.5 for a bed and stingers; edit manually after generation.
""",
        )
        paths.append(music_path)
        return paths

    def _write_edit_package(self, movie: dict[str, Any], shots: list[dict[str, Any]]) -> list[Path]:
        edl_path = self.movie_root / "edit" / "edit_decision_list.csv"
        concat_path = self.movie_root / "edit" / "ffmpeg_concat.txt"
        assemble_path = self.movie_root / "edit" / "assemble_ffmpeg.sh"
        checklist_path = self.movie_root / "edit" / "editor_checklist.md"

        with edl_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "order",
                    "shot_id",
                    "scene_title",
                    "duration_seconds",
                    "preferred_video",
                    "dialogue_audio",
                    "mix_audio",
                    "notes",
                ],
            )
            writer.writeheader()
            for index, shot in enumerate(shots, start=1):
                writer.writerow(
                    {
                        "order": index,
                        "shot_id": shot["shot_id"],
                        "scene_title": shot["scene_title"],
                        "duration_seconds": shot["duration_seconds"],
                        "preferred_video": shot["video_lipsynced_path"],
                        "dialogue_audio": shot["dialogue_audio_path"],
                        "mix_audio": shot["mix_audio_path"],
                        "notes": shot.get("continuity_notes", ""),
                    }
                )

        concat_lines = [
            "# Replace paths with approved rendered clips if needed.",
            "# ffmpeg concat demuxer format:",
        ]
        for shot in shots:
            concat_lines.append(f"file '../renders/video_lipsynced/{shot['shot_id']}_lipsync.mp4'")
        self._safe_write(concat_path, "\n".join(concat_lines) + "\n")
        self._safe_write(assemble_path, _assemble_script(movie))
        assemble_path.chmod(0o755)
        self._safe_write(checklist_path, _editor_checklist(movie, shots))
        return [edl_path, concat_path, assemble_path, checklist_path]

    def _write_review_files(self, shots: list[dict[str, Any]]) -> list[Path]:
        paths: list[Path] = []
        for shot in shots:
            path = self.movie_root / "review" / f"{shot['shot_id']}_review.md"
            lines = [
                f"# {shot['shot_id']} Review",
                "",
                f"Scene: {shot.get('scene_title', '')}",
                f"Duration: {shot.get('duration_seconds', '')} seconds",
                "",
                "## Approval",
                "",
                "- [ ] Character continuity passes",
                "- [ ] No readable passwords, UI text, logos, or accidental captions",
                "- [ ] Motion supports the story beat",
                "- [ ] Dialogue timing feels natural",
                "- [ ] Lip-sync checked when dialogue is present",
                "- [ ] Audio mix is clear and child-safe",
                "",
                "## Notes",
                "",
                "- ",
            ]
            self._safe_write(path, "\n".join(lines) + "\n")
            paths.append(path)
        return paths

    def _write_build_report(self, movie: dict[str, Any], result: MovieBuildResult) -> Path:
        path = self.movie_root / "reports" / "movie_build_report.md"
        text = f"""# Movie Build Report

Movie: {movie["title"]}

- Slug: {movie["slug"]}
- Shots processed: {result.shot_count}
- Target runtime: {movie.get("runtime_seconds", "unknown")} seconds
- Resolution: {movie.get("resolution", "1920x1080")}
- FPS: {movie.get("fps", 24)}
- Force: {self.options.force}
- Dry run: {self.options.dry_run}

## Generated Folders

- shots
- prompts/keyframes
- prompts/video
- audio/dialogue
- audio/sfx
- audio/music
- renders/keyframes
- renders/video_raw
- renders/video_lipsynced
- edit
- review
"""
        self._safe_write(path, text)
        return path

    def _write_model_handoff(self, movie: dict[str, Any]) -> Path:
        path = self.movie_root / "reports" / "model_handoff.md"
        models = movie.get("models", DEFAULT_MOVIE_MODELS)
        lines = ["# Model Handoff", ""]
        for role, model in models.items():
            lines.append(f"- {role}: {model}")
        lines.extend(
            [
                "",
                "## Recommended Order",
                "",
                "1. Generate or approve one keyframe per shot.",
                "2. Run image-to-video from approved keyframes.",
                "3. Generate dialogue audio from `audio/dialogue/*.txt`.",
                "4. Lip-sync only dialogue shots.",
                "5. Generate music bed and SFX, then mix per shot.",
                "6. Assemble approved clips using `edit/edit_decision_list.csv`.",
            ]
        )
        self._safe_write(path, "\n".join(lines) + "\n")
        return path

    def _limit(self, shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.options.limit_shots is None:
            return shots
        return shots[: max(0, min(len(shots), self.options.limit_shots))]

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.project_root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def _safe_write(self, path: Path, content: str) -> None:
        if path.exists() and not self.options.force:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _ns(data: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(**data)

    def _print_summary(self, result: MovieBuildResult) -> None:
        self.console.print(f"[green]Movie package ready for {result.movie_slug}.[/green]")
        self.console.print(f"Shots processed: {result.shot_count}")
        self.console.print(f"Movie root: {result.movie_root}")
        self.console.print(f"Edit package: {result.movie_root / 'edit'}")
        self.console.print(f"Review folder: {result.movie_root / 'review'}")


def default_movie_data() -> dict[str, Any]:
    return {
        "title": "Hackster Niko and the Password Dragon: Teaser",
        "series": "Hackster Niko",
        "slug": "password_dragon_teaser",
        "source_book": "book01_password_dragon",
        "format": "short_film",
        "runtime_seconds": 75,
        "target_age": "5-8",
        "resolution": "1920x1080",
        "aspect_ratio": "16:9",
        "fps": 24,
        "delivery": ["YouTube 1080p", "social cutdowns"],
        "lesson": "Strong passwords are long, silly, and secret.",
        "tone": "Warm, clever, playful, reassuring, wonder-filled, emotionally safe.",
        "niko_consistency": DEFAULT_NIKO_CONSISTENCY,
        "global_visual_style": DEFAULT_STYLE,
        "negative_prompt": (
            "text, letters, captions, subtitles, readable passwords, logos, brand names, UI, scary imagery, "
            "weapons, sharp teeth, realistic threat, horror lighting, extra limbs, tail, mouth on Niko"
        ),
        "music_direction": "Warm child-safe adventure score with light marimba, soft synth, bells, and gentle percussion.",
        "models": DEFAULT_MOVIE_MODELS,
        "shots": DEFAULT_MOVIE_SHOTS,
    }


def _dialogue_lines(shot: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    narration = str(shot.get("narration", "")).strip()
    if narration:
        lines.append(f"Narrator: {narration}")
    for line in shot.get("dialogue", []):
        speaker = line.get("speaker", "Speaker")
        text = line.get("text", "")
        lines.append(f"{speaker}: {text}")
    return lines


def _assemble_script(movie: dict[str, Any]) -> str:
    fps = int(movie.get("fps", 24))
    resolution = str(movie.get("resolution", "1920x1080"))
    return f"""#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p renders/final

ffmpeg -y \\
  -f concat \\
  -safe 0 \\
  -i edit/ffmpeg_concat.txt \\
  -r {fps} \\
  -s {resolution} \\
  -c:v libx264 \\
  -pix_fmt yuv420p \\
  -movflags +faststart \\
  renders/final/{movie["slug"]}_picture_lock.mp4

echo "Wrote renders/final/{movie["slug"]}_picture_lock.mp4"
echo "Mix final music/dialogue/SFX in your editor, or mux a final WAV with:"
echo "ffmpeg -i renders/final/{movie["slug"]}_picture_lock.mp4 -i audio/mixes/final_mix.wav -c:v copy -c:a aac renders/final/{movie["slug"]}_final.mp4"
"""


def _editor_checklist(movie: dict[str, Any], shots: list[dict[str, Any]]) -> str:
    total_duration = sum(float(shot.get("duration_seconds", 0)) for shot in shots)
    return f"""# Editor Checklist

Movie: {movie["title"]}

Target runtime: {movie.get("runtime_seconds", total_duration)} seconds
Current shot total: {total_duration:g} seconds

## Picture Lock

- [ ] Every clip matches the EDL order.
- [ ] No clip contains readable passwords, accidental UI, captions, watermarks, or logos.
- [ ] Niko keeps the locked HN-01 design in every shot.
- [ ] Cuts preserve story clarity for ages {movie.get("target_age", "5-8")}.
- [ ] Teaser ending lands cleanly.

## Audio Lock

- [ ] Dialogue is intelligible at low volume.
- [ ] Music supports the emotional beat without burying dialogue.
- [ ] SFX are friendly, gentle, and not startling.
- [ ] Final mix has no clipping.

## Export

- [ ] 1920x1080 H.264 review export.
- [ ] Archive project files, prompts, approved keyframes, rendered clips, and final WAV.
"""


def build_movie_package(movie_yaml: Path, options: MovieBuildOptions, console: Console | None = None) -> MovieBuildResult:
    return MovieBuildPipeline(movie_yaml, options, console=console).run()
