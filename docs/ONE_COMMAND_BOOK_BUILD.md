# One-Command Book Build

Hackster Studio can build a complete editable draft package for **Hackster Niko and the Password Dragon** from one YAML file.

The automation creates:

- 32 page YAML specs
- page illustration prompts
- optional OpenAI Image API illustrations
- image validation reports
- per-page review files
- a draft interior PDF
- an Affinity Publisher handoff package
- production reports and approval checklists

It does not publish anything and does not upload to Lulu.

## Install Requirements

From the `HacksterNiko` project root:

```bash
python -m pip install -r requirements.txt
```

If your system Python is externally managed, use a local virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Set OpenAI API Key

Image generation is optional and only runs with `--generate-images`.

Copy the example environment file:

```bash
cp .env.example .env
```

Then set:

```text
OPENAI_API_KEY=your_key_here
OPENAI_IMAGE_MODEL=gpt-image-1
```

`OPENAI_IMAGE_MODEL` is configurable. Change it in `.env` when you want a different supported image model.

## Dry Run

```bash
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --dry-run
```

Dry-run mode plans the build and does not call the OpenAI API.

## Build Draft Without Images

```bash
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --no-images --build-pdf
```

This creates prompts, review files, reports, Affinity package files, and a draft PDF with placeholders for missing images.

## Build With Image Generation

Using the configured default backend from `.env`:

```bash
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --generate-images --build-pdf
```

Using your local DGX ComfyUI backend explicitly:

```bash
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --generate-images --image-backend comfyui --build-pdf
```

Existing files are skipped. Use `--force` to overwrite generated files:

```bash
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --generate-images --build-pdf --force
```

For a quick test:

```bash
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --no-images --build-pdf --limit-pages 3
```

## Where Files Appear

- Page specs: `books/book01_password_dragon/pages/`
- Prompts: `books/book01_password_dragon/prompts/`
- Illustrations: `books/book01_password_dragon/illustrations/`
- Review files: `books/book01_password_dragon/review/`
- Affinity package: `books/book01_password_dragon/affinity_package/`
- Draft PDF: `books/book01_password_dragon/pdf/book01_password_dragon_draft.pdf`
- Reports: `books/book01_password_dragon/reports/`

## ComfyUI Backend

Set these in `.env`:

```text
HACKSTER_IMAGE_BACKEND=comfyui
COMFYUI_URL=http://192.168.68.136:8188
COMFYUI_WORKFLOW_PATH=
COMFYUI_CHECKPOINT=sd_xl_base_1.0.safetensors
```

If ComfyUI is behind a trusted LAN auth proxy, set:

```text
COMFYUI_USERNAME=your_username
COMFYUI_PASSWORD=your_password
```

Do not commit `.env`.

If `COMFYUI_WORKFLOW_PATH` is empty, Hackster Studio sends a simple built-in SDXL-style workflow. The checkpoint named by `COMFYUI_CHECKPOINT` must exist in ComfyUI's checkpoint folder. For custom FLUX/SDXL workflows, export the workflow in ComfyUI API format, save it locally, and point `COMFYUI_WORKFLOW_PATH` to that JSON file.

## Review Images

Open each `review/page_###_review.md` file. Check:

- Niko consistency
- no accidental text in the image
- child-friendly tone
- correct characters and scene
- hidden objects included
- enough empty space for story text
- no scary imagery
- print resolution acceptable

## Production QA Gate

Before running a full 32-page image generation pass, create and approve a one-page pilot.
The build command blocks full production image generation until the pilot page passes
technical validation and has `approval_status: approved`.

Generate the pilot:

```bash
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --generate-images --image-backend comfyui --limit-pages 1 --force
```

Check the gate report:

```bash
python -m hackster_studio.cli qa-gate books/book01_password_dragon/book.yaml
```

The report is written to:

```text
books/book01_password_dragon/reports/production_gate_report.md
```

Approve the pilot only after visual QA confirms:

- Niko has no mouth or mouth-like mark
- no text-like marks anywhere in the image
- no hoodie, cuff, shoe, tool, or environment labels
- Core Crystal is clean and non-symbolic
- no gridlines, tile seams, halftone, or moire artifacts
- image is sharp enough for the 8.5 x 8.5 inch book
- composition leaves safe editable text space

After approval:

```bash
python -m hackster_studio.cli approve-page book01_password_dragon 1
python -m hackster_studio.cli qa-gate books/book01_password_dragon/book.yaml
```

Only then run full production:

```bash
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml --generate-images --image-backend comfyui --build-pdf
```

## Replace Or Regenerate Bad Images

To replace a page manually, save a corrected PNG over:

```text
books/book01_password_dragon/illustrations/page_###.png
```

To regenerate with the API, delete or move the bad image, then rerun with `--generate-images`, or use `--force` if you intentionally want to overwrite generated files.

## Open Draft PDF

Open:

```text
books/book01_password_dragon/pdf/book01_password_dragon_draft.pdf
```

The PDF is for reading and review. Story text is added as selectable PDF text, not baked into the illustration.

## Assemble In Affinity Publisher

Use `books/book01_password_dragon/affinity_package/` as the handoff folder. Each page includes:

- `page.yaml`
- `story_text.txt`
- `illustration_path.txt`
- `layout.json`

Create a 32-page 8.5 x 8.5 inch Affinity Publisher document with 0.125 inch bleed and 0.5 inch margins. Place illustrations full bleed and add story text as editable text boxes.

## Approval Flow

Mark a page approved after human review:

```bash
python -m hackster_studio.cli approve-page book01_password_dragon 4
```

Check package status:

```bash
python -m hackster_studio.cli status-book book01_password_dragon
```
