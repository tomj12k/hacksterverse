# Publishing Specs

## Book Format

- Trim size: 8.5 x 8.5 inches
- Page count: 32 pages
- Resolution: 300 DPI
- Bleed: 0.125 inch
- Safe margins: 0.5 inch
- Primary platform: Lulu Direct
- Future compatibility: KDP and IngramSpark

## Page Setup

For full-bleed pages:

- Artboard/page size with bleed: 8.75 x 8.75 inches
- Final trim size: 8.5 x 8.5 inches
- Keep critical text and character faces inside the 0.5 inch safe margin.

## Export Targets

Lulu first:

- Interior PDF
- Full-wrap cover PDF or platform-required cover file
- Proof copy before public release

Future:

- KDP-compatible interior and cover exports
- IngramSpark-compatible interior and cover exports

## Recommended Production Workflow

1. Write manuscript in `03_Books/Book01_PasswordDragon/Manuscript/`.
2. Create storyboard thumbnails in `Storyboard/`.
3. Build rough page layouts in `PageLayouts/`.
4. Create final illustrations in `Illustrations/`.
5. Assemble the book in Affinity Publisher in `Affinity/`.
6. Export platform PDFs to `Exports/`.
7. Copy submission-ready Lulu files to `05_Print/Lulu/`.
8. Record proof notes in `05_Print/Proofs/`.

## Quality Checks Before Lulu Upload

- [ ] Page count is exactly 32 pages.
- [ ] Trim size is 8.5 x 8.5 inches.
- [ ] Bleed is set to 0.125 inch.
- [ ] Text stays inside 0.5 inch safe margins.
- [ ] Images are 300 DPI at placed size.
- [ ] Fonts are embedded or handled according to license.
- [ ] No accidental RGB/CMYK surprises after export review.
- [ ] Cover spine width matches Lulu calculator.
- [ ] PDF opens cleanly and pages are in correct order.

## TODO

- TODO: Confirm Lulu paper, binding, and cover finish.
- TODO: Add KDP export differences after Lulu template is stable.
- TODO: Add IngramSpark export differences after Book 01 proof.

