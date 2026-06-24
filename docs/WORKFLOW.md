# Hackster Studio Workflow

## 1. Seed The Project

Run:

```bash
python -m hackster_studio.cli seed
```

This creates the starter Hackster Niko project, Niko character record, Cyber Forest environment, Code Scanner gadget, and Book 01 record.

## 2. Plan The Book

Run:

```bash
python -m hackster_studio.cli plan-book book01_password_dragon
```

The planner creates 32 page records:

- Page 1: Title page
- Page 2: Copyright
- Page 3: Dedication
- Pages 4-29: Story pages
- Page 30: The End
- Page 31: Password Challenge activity
- Page 32: Suspicious email teaser for Book 2

## 3. Edit Story And Illustration Notes

Use the web app page detail screen to edit story text and illustration direction. Keep story text editable in layout; do not ask image generation tools to render words into the image.

## 4. Generate Prompts

Run:

```bash
python -m hackster_studio.cli generate-prompts book01_password_dragon
```

Review the Markdown prompts in `data/generated/prompts/pages/book01_password_dragon/`.

## 5. Generate Images Manually

Paste reviewed prompts into the image generation tool. Save selected image files into:

```text
assets/illustrations/
```

Use clear names such as:

```text
HN_Book01_Page04_Illustration_v001.png
```

## 6. Validate Print Readiness

Run:

```bash
python -m hackster_studio.cli print-check assets/illustrations/HN_Book01_Page04_Illustration_v001.png
```

Full-bleed page art should be at least `2625 x 2625 px` with 300 DPI metadata.

## 7. Build In Affinity Publisher

Place images full bleed, then add story text as editable text boxes inside the safe margin.

