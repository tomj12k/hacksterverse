# Hackster Studio

Hackster Studio is a local children’s book publishing platform for building the Hackster Niko series first, while staying reusable for future picture book projects.

It helps manage:

- Character Library
- World / Environment Library
- Gadget Library
- Book Planner
- Story Engine
- Prompt Generator
- Illustration Tracker
- Page Layout Manager
- Print Validator
- Publishing Dashboard
- Project Status Tracker

Hackster Studio does not generate images and does not call external APIs. It creates organized records, prompts, YAML page specs, and print readiness reports for a human publishing workflow.

## Install

From the `HacksterNiko` project root:

```bash
python -m pip install -r requirements.txt
```

## First Run

```bash
python -m hackster_studio.cli init-db
python -m hackster_studio.cli seed
python -m hackster_studio.cli plan-book book01_password_dragon
python -m hackster_studio.cli generate-prompts book01_password_dragon
python -m hackster_studio.cli export-yaml book01_password_dragon
python -m hackster_studio.cli status
```

## Run The Web App

```bash
python -m hackster_studio.cli run
```

Open:

```text
http://127.0.0.1:8000
```

## Output Locations

- Page prompts: `data/generated/prompts/pages/book01_password_dragon/`
- Character/environment/gadget prompts: `data/generated/prompts/`
- YAML page specs: `data/generated/page_specs/book01_password_dragon/`
- Print reports: stored in the SQLite database and visible in the Print Validator.
- Artwork source folders: `assets/`

## Manual Production Step

After prompts are generated, paste them into the image generation tool of choice. Save selected images into `assets/illustrations/`, then place final art in Affinity Publisher for layout and export.

