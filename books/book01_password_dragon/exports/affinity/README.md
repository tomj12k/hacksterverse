# Affinity Handoff

## Verified Path: PDF Import

Affinity 3.2.2 on this Mac does not register `.idml` as an openable document type. The verified automated handoff is the Lulu production PDF:

```text
../lulu/book01_password_dragon_interior_lulu_print_v2_title_shadow.pdf
```

Open it with:

```bash
PYTHONPATH=. .venv/bin/python -m hackster_studio.cli open-affinity books/book01_password_dragon/book.yaml
```

Affinity imports the PDF as 32 pages with the full-page artwork and editable text layers. After import, immediately save it as:

```text
book01_password_dragon.afpub
```

## Experimental Path: IDML

`book01_password_dragon_affinity_starter.idml` is still generated as an experimental starter package. It includes:

- 32 single-page spreads at 8.75 x 8.75 inches for bleed-aware layout.
- Linked full-bleed PNG illustrations in the IDML `Links/` folder.
- Editable text stories for each page.
- Starter paragraph styles and Hackster Niko color swatches.

Use this only if Affinity adds direct IDML support or if a known-good Affinity/InDesign IDML template is available for mutation.

## Production Notes

- Treat the imported Affinity document as a starting point, not the final approved `.afpub`.
- Replace draft story-beat copy with final manuscript text.
- Apply final children’s-book typography, panels, outlines, shadows, and page-specific text art inside Affinity.
- Review every generated illustration for unwanted text-like marks, signatures, mouths, or character drift before approval.
- Export the final Lulu PDF from Affinity after visual proofing.
