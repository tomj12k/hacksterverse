# Hackster Niko

Professional production workspace for the children's book franchise **Hackster Niko**, beginning with:

**Hackster Niko and the Password Dragon**

Hackster Niko is a small friendly learning robot, model HN-01, 2'6" tall, age equivalent 7, he/him, and a Junior Hackster.

Catchphrase: **"Every problem has a clever fix!"**

## Franchise Mission

Inspire kids to solve problems with kindness, curiosity, creativity, teamwork, and responsible technology.

## Directory Map

- `00_BrandBible/` - mission, values, story rules, art direction, color, type, and publishing specs.
- `01_Characters/` - character reference, model sheets, turnarounds, expressions, poses, gadgets, and visual continuity.
- `02_World/` - recurring locations, environment references, maps, props, and worldbuilding notes.
- `03_Books/` - book-specific production folders, starting with `Book01_PasswordDragon`.
- `04_Assets/` - reusable franchise assets such as logos, icons, hidden objects, props, textures, and gadgets.
- `05_Print/` - printer/platform-specific exports, proofs, and submission notes.
- `06_Marketing/` - website, social, press kit, and merchandise materials.
- `movies/` - shot-based movie packages, prompts, audio cues, edit lists, and rendered clips.
- `99_Archive/` - retired drafts, superseded exports, and historical materials that should not be active production sources.

## Recommended Asset Naming Convention

Use clear, sortable names:

`HN_[Category]_[Subject]_[Descriptor]_[Version].[ext]`

Examples:

- `HN_Character_Niko_Turnaround_v001.png`
- `HN_Character_Niko_HappyExpression_v002.afdesign`
- `HN_HiddenObject_GoldenGear_Final_v001.png`
- `HN_Book01_Page07_Illustration_Color_v003.afdesign`
- `HN_Book01_Cover_FullWrap_Lulu_v001.afpub`
- `HN_Book01_PrintInterior_Lulu_8p5x8p5_v001.pdf`

Guidelines:

- Use two-digit page numbers: `Page01`, `Page02`, `Page32`.
- Use platform names in print exports: `Lulu`, `KDP`, `IngramSpark`.
- Use version numbers instead of overwriting: `v001`, `v002`, `v003`.
- Add `FINAL` only after approval, and keep the version number: `HN_Book01_Interior_Lulu_FINAL_v003.pdf`.
- Avoid spaces and special characters in production filenames.

## Production Workflow

1. Story
   - Draft manuscript in `03_Books/Book01_PasswordDragon/Manuscript/`.
   - Track page count, read-aloud rhythm, vocabulary, and story-rule compliance.

2. Storyboard
   - Create page-by-page thumbnails in `Storyboard/`.
   - Confirm page turns, hidden object placement, emotional beats, and pacing.

3. Page Layout
   - Build rough page compositions in `PageLayouts/`.
   - Check safe margins, bleed, text placement, and room for illustration.

4. Illustration
   - Produce final art in `Illustrations/`.
   - Keep source files versioned and export review images separately when needed.

5. Affinity Publisher
   - Assemble the book in `Affinity/`.
   - Link or place approved illustration exports.
   - Confirm page size, bleed, margins, typography, and embedded/outlined fonts as needed.

6. Lulu PDF
   - Export print-ready PDFs to `Exports/`.
   - Copy Lulu-ready deliverables and submission notes to `05_Print/Lulu/`.
   - Order proof copies and record findings in `05_Print/Proofs/`.

## Movie Workflow

Build the starter film package with:

```bash
.venv/bin/python -m hackster_studio.cli build-movie-package movies/password_dragon_teaser/movie.yaml
```

See `docs/MOVIE_PIPELINE.md` for the DGX/ComfyUI, video, dialogue, lip-sync, audio, and editing workflow.

## Hidden Objects

Recurring hidden objects to include on pages:

- Golden Gear
- Tiny Bug
- Blue Crystal
- Mini Robot

TODO: Create canonical visual references for each hidden object in `04_Assets/HiddenObjects/`.

## Git Notes

- Keep source files, Markdown notes, and approved exports versioned.
- Avoid committing temporary app files, duplicate exports, or unmanaged downloads.
- Do not add placeholder binary/image files.
- Use `99_Archive/` for old work that must be preserved but should not drive current production.
