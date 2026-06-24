# Hackster Asset Generator

The Hackster Asset Generator is a local Python tool for the **Hackster Niko** publishing pipeline.

It reads structured YAML files for characters, environments, gadgets, and book pages, then generates:

- Image-generation prompt files
- Metadata manifest JSON files
- Production review checklists

It does **not** generate images directly. The generated prompts are meant to be reviewed by a human, edited if needed, then pasted into an image generation tool.

## Requirements

- Python 3.11+
- `pyyaml`
- `jinja2`
- `jsonschema`
- `rich`

Install dependencies from the `HacksterNiko` project root:

```bash
python -m pip install -r tools/asset_generator/requirements.txt
```

## Run The Tool

From the `HacksterNiko` project root:

```bash
python tools/asset_generator/generate_assets.py --input tools/asset_generator/examples/niko.character.yaml
```

You can also run it from the parent workspace by including the project folder:

```bash
python HacksterNiko/tools/asset_generator/generate_assets.py --input HacksterNiko/tools/asset_generator/examples/niko.character.yaml
```

## Example Commands

```bash
python tools/asset_generator/generate_assets.py --input tools/asset_generator/examples/byte.character.yaml
python tools/asset_generator/generate_assets.py --input tools/asset_generator/examples/password_dragon.character.yaml
python tools/asset_generator/generate_assets.py --input tools/asset_generator/examples/cyber_forest.environment.yaml
python tools/asset_generator/generate_assets.py --input tools/asset_generator/examples/code_scanner.gadget.yaml
```

## Expected Outputs

For an input like:

```bash
tools/asset_generator/examples/niko.character.yaml
```

The tool writes:

- `generated_assets/prompts/character/niko/`
- `generated_assets/manifests/niko.manifest.json`
- `generated_assets/checklists/niko.checklist.md`

Character specs generate three prompt files:

- Turnaround sheet prompt
- Expression sheet prompt
- Pose sheet prompt

Environment, gadget, and book page specs each generate one prompt file.

## Supported Asset Types

- `character`
- `environment`
- `gadget`
- `book_page`

Each asset type has a matching JSON schema in `schemas/`.

## Add A New Character

1. Copy `tools/asset_generator/examples/niko.character.yaml`.
2. Save it in `asset_specs/characters/`.
3. Change `name`, `slug`, `version`, and all character-specific fields.
4. Keep `asset_type: character`.
5. Run:

```bash
python tools/asset_generator/generate_assets.py --input asset_specs/characters/your_character.character.yaml
```

Beginner tip: keep `slug` lowercase with underscores, such as `firewall_fox`.

## Add A New Book Page

1. Create a YAML file in `asset_specs/book_pages/`.
2. Set `asset_type: book_page`.
3. Include page number, scene summary, characters, setting, composition, text-space notes, hidden objects, art style, and print specs.
4. Run:

```bash
python tools/asset_generator/generate_assets.py --input asset_specs/book_pages/book01_page01.book_page.yaml
```

Minimum page print specs should include:

```yaml
print_specs:
  trim_size: 8.5 x 8.5 inches
  dpi: 300
  bleed: 0.125 inch
  safe_margin: 0.5 inch
```

## Using Generated Prompts

1. Open the generated prompt Markdown file.
2. Review it against the generated checklist.
3. Edit the prompt if a page, character, or prop needs extra production notes.
4. Paste the prompt into the chosen image generation tool.
5. Save selected outputs using the recommended filename prefix from the manifest.
6. Place approved artwork into the relevant production folder, such as:
   - `01_Characters/Niko/`
   - `02_World/CyberForest/`
   - `03_Books/Book01_PasswordDragon/Illustrations/`
   - `04_Assets/Gadgets/`

## Production Notes

- Keep YAML specs as the source of truth for prompt generation.
- Version source YAML and generated prompts in Git.
- Do not commit temporary downloads or unreviewed bulk image output.
- Use manifests to connect generated prompt files back to their source YAML.
- Use checklists before moving art into Affinity Publisher.

