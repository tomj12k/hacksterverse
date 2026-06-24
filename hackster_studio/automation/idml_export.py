"""Create an IDML starter package for Affinity Publisher handoff."""

from __future__ import annotations

import shutil
import zipfile
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from reportlab.lib.units import inch


IDML_MIMETYPE = "application/vnd.adobe.indesign-idml-package"
IDML_NS = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"


def create_idml_package(
    *,
    book: dict[str, Any],
    pages: list[dict[str, Any]],
    output_path: Path,
    force: bool = False,
) -> Path:
    """Create an IDML package with one full-bleed image and editable text per page."""
    if output_path.exists() and not force:
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="hackster_idml_") as tmp:
        package_root = Path(tmp)
        _write_idml_tree(package_root, book, pages)
        _zip_idml(package_root, output_path)
    return output_path


def _write_idml_tree(root: Path, book: dict[str, Any], pages: list[dict[str, Any]]) -> None:
    for dirname in ["META-INF", "Resources", "MasterSpreads", "Spreads", "Stories", "Links", "XML"]:
        (root / dirname).mkdir(parents=True, exist_ok=True)

    (root / "mimetype").write_text(IDML_MIMETYPE, encoding="utf-8")
    (root / "META-INF" / "container.xml").write_text(_container_xml(), encoding="utf-8")
    (root / "XML" / "BackingStory.xml").write_text(_backing_story_xml(), encoding="utf-8")
    (root / "XML" / "Tags.xml").write_text(_tags_xml(), encoding="utf-8")
    (root / "XML" / "Mapping.xml").write_text(_mapping_xml(), encoding="utf-8")
    (root / "Resources" / "Preferences.xml").write_text(_preferences_xml(book, len(pages)), encoding="utf-8")
    (root / "Resources" / "Styles.xml").write_text(_styles_xml(), encoding="utf-8")
    (root / "Resources" / "Fonts.xml").write_text(_fonts_xml(), encoding="utf-8")
    (root / "Resources" / "Graphic.xml").write_text(_graphic_xml(), encoding="utf-8")

    page_width, page_height = _full_bleed_points(book)
    (root / "MasterSpreads" / "MasterSpread_A.xml").write_text(
        _master_spread_xml(page_width=page_width, page_height=page_height),
        encoding="utf-8",
    )
    design_refs: list[str] = [
        '<idPkg:BackingStory src="XML/BackingStory.xml"/>',
        '<idPkg:Tags src="XML/Tags.xml"/>',
        '<idPkg:Mapping src="XML/Mapping.xml"/>',
        '<idPkg:Preferences src="Resources/Preferences.xml"/>',
        '<idPkg:Styles src="Resources/Styles.xml"/>',
        '<idPkg:Fonts src="Resources/Fonts.xml"/>',
        '<idPkg:Graphic src="Resources/Graphic.xml"/>',
        '<idPkg:MasterSpread src="MasterSpreads/MasterSpread_A.xml"/>',
    ]
    story_ids: list[str] = []

    for page in pages:
        page_number = int(page["page_number"])
        story_id = _story_id(page_number)
        spread_id = _spread_id(page_number)
        story_ids.append(story_id)
        link_name = f"page_{page_number:03d}.png"
        image_source = Path(str(page.get("illustration_path", "")))
        link_target = root / "Links" / link_name
        if image_source.exists():
            shutil.copy2(image_source, link_target)

        (root / "Stories" / f"Story_{page_number:03d}.xml").write_text(
            _story_xml(page, story_id),
            encoding="utf-8",
        )
        (root / "Spreads" / f"Spread_{page_number:03d}.xml").write_text(
            _spread_xml(
                page=page,
                spread_id=spread_id,
                story_id=story_id,
                link_name=link_name,
                page_width=page_width,
                page_height=page_height,
            ),
            encoding="utf-8",
        )
        design_refs.append(f'<idPkg:Story src="Stories/Story_{page_number:03d}.xml"/>')
        design_refs.append(f'<idPkg:Spread src="Spreads/Spread_{page_number:03d}.xml"/>')

    (root / "designmap.xml").write_text(_designmap_xml(book, design_refs, story_ids), encoding="utf-8")


def _zip_idml(package_root: Path, output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        mimetype = package_root / "mimetype"
        archive.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
        for path in sorted(package_root.rglob("*")):
            if path.is_file() and path != mimetype:
                archive.write(path, path.relative_to(package_root).as_posix())


def _full_bleed_points(book: dict[str, Any]) -> tuple[float, float]:
    full_bleed = str(book.get("full_bleed_inches", "8.75x8.75")).lower().replace(" ", "")
    width, height = full_bleed.split("x", 1)
    return float(width) * inch, float(height) * inch


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="designmap.xml" media-type="application/vnd.adobe.indesign-idml-package+xml"/>
  </rootfiles>
</container>
"""


def _designmap_xml(book: dict[str, Any], refs: list[str], story_ids: list[str]) -> str:
    title = escape(str(book.get("title", "Hackster Niko Book")))
    joined_refs = "\n  ".join(refs)
    story_list = " ".join(story_ids)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Document xmlns:idPkg="{IDML_NS}" DOMVersion="8.0" Self="d" Name="{title}" StoryList="{story_list}" ActiveLayer="layer1" ZeroPoint="0 0">
  <Layer Self="layer1" Name="Layer 1" Visible="true" Locked="false" IgnoreWrap="false" ShowGuides="true" LockGuides="false" UI="true" Printable="true"/>
  {joined_refs}
</Document>
"""


def _preferences_xml(book: dict[str, Any], page_count: int) -> str:
    page_width, page_height = _full_bleed_points(book)
    bleed = float(book.get("bleed_inches", 0.125)) * inch
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Preferences xmlns:idPkg="{IDML_NS}" DOMVersion="8.0">
  <DocumentPreference Self="DocumentPreference" PageWidth="{page_width:g}" PageHeight="{page_height:g}" PagesPerDocument="{page_count}" FacingPages="false" Intent="PrintIntent"/>
  <MarginPreference Self="MarginPreference" Top="45" Bottom="45" Left="45" Right="45"/>
  <BleedPreference Self="BleedPreference" Top="{bleed:g}" Bottom="{bleed:g}" Left="{bleed:g}" Right="{bleed:g}"/>
</idPkg:Preferences>
"""


def _styles_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Styles xmlns:idPkg="{IDML_NS}" DOMVersion="8.0">
  <RootParagraphStyleGroup Self="RootParagraphStyleGroup">
    <ParagraphStyle Self="ParagraphStyle/HN Title" Name="HN Title" PointSize="28" AppliedFont="Helvetica" FontStyle="Bold" FillColor="Color/Hackster Blue" Justification="CenterAlign"/>
    <ParagraphStyle Self="ParagraphStyle/HN Story" Name="HN Story" PointSize="13" AppliedFont="Helvetica" FontStyle="Regular" FillColor="Color/Dark Outline" Justification="LeftAlign"/>
    <ParagraphStyle Self="ParagraphStyle/HN Callout" Name="HN Callout" PointSize="18" AppliedFont="Helvetica" FontStyle="Bold" FillColor="Color/Dark Outline" Justification="CenterAlign"/>
  </RootParagraphStyleGroup>
  <RootCharacterStyleGroup Self="RootCharacterStyleGroup"/>
  <Color Self="Color/Hackster Blue" Name="Hackster Blue" Space="RGB" ColorValue="71 199 255" ColorOverride="Normal"/>
  <Color Self="Color/Core Crystal" Name="Core Crystal" Space="RGB" ColorValue="99 223 255" ColorOverride="Normal"/>
  <Color Self="Color/Friendly White" Name="Friendly White" Space="RGB" ColorValue="248 252 255" ColorOverride="Normal"/>
  <Color Self="Color/Dark Outline" Name="Dark Outline" Space="RGB" ColorValue="57 74 99" ColorOverride="Normal"/>
  <Color Self="Color/Golden Gear" Name="Golden Gear" Space="RGB" ColorValue="242 201 76" ColorOverride="Normal"/>
</idPkg:Styles>
"""


def _fonts_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Fonts xmlns:idPkg="{IDML_NS}" DOMVersion="8.0">
  <FontFamily Self="FontFamily/Helvetica" Name="Helvetica"/>
</idPkg:Fonts>
"""


def _graphic_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Graphic xmlns:idPkg="{IDML_NS}" DOMVersion="8.0"/>
"""


def _backing_story_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:BackingStory xmlns:idPkg="{IDML_NS}" DOMVersion="8.0">
  <Story Self="BackingStory"/>
</idPkg:BackingStory>
"""


def _tags_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Tags xmlns:idPkg="{IDML_NS}" DOMVersion="8.0">
  <XMLTag Self="XMLTag/Root" Name="Root" MarkupTagColor="UIColors/Gray"/>
</idPkg:Tags>
"""


def _mapping_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Mapping xmlns:idPkg="{IDML_NS}" DOMVersion="8.0"/>
"""


def _master_spread_xml(*, page_width: float, page_height: float) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:MasterSpread xmlns:idPkg="{IDML_NS}" DOMVersion="8.0">
  <MasterSpread Self="masterspreadA" NamePrefix="A" BaseName="Master" ShowMasterItems="true" PageCount="1" BindingLocation="0">
    <Page Self="masterpageA" Name="A" GeometricBounds="0 0 {page_height:g} {page_width:g}" ItemTransform="1 0 0 1 0 0"/>
  </MasterSpread>
</idPkg:MasterSpread>
"""


def _story_xml(page: dict[str, Any], story_id: str) -> str:
    page_type = str(page.get("page_type", "story"))
    style = "HN Title" if page_type == "title_page" else "HN Story"
    if page_type == "ending":
        style = "HN Callout"
    text = escape(str(page.get("story_text", "")).strip())
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Story xmlns:idPkg="{IDML_NS}" DOMVersion="8.0">
  <Story Self="{story_id}">
    <ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/{style}">
      <CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
        <Content>{text}</Content>
      </CharacterStyleRange>
    </ParagraphStyleRange>
  </Story>
</idPkg:Story>
"""


def _spread_xml(
    *,
    page: dict[str, Any],
    spread_id: str,
    story_id: str,
    link_name: str,
    page_width: float,
    page_height: float,
) -> str:
    page_number = int(page["page_number"])
    image_id = f"img{page_number:03d}"
    image_frame_id = f"rect{page_number:03d}"
    panel_id = f"panel{page_number:03d}"
    text_frame_id = f"text{page_number:03d}"
    text_bounds = _text_bounds(page, page_width, page_height)
    story_panel = _story_panel_xml(panel_id, text_bounds, page)
    story_frame = _text_frame_xml(text_frame_id, story_id, text_bounds)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Spread xmlns:idPkg="{IDML_NS}" DOMVersion="8.0">
  <Spread Self="{spread_id}" PageCount="1" BindingLocation="0" AllowPageShuffle="true" ItemTransform="1 0 0 1 0 0">
    <Page Self="page{page_number:03d}" Name="{page_number}" AppliedMaster="masterspreadA" MasterPageTransform="1 0 0 1 0 0" GeometricBounds="0 0 {page_height:g} {page_width:g}" ItemTransform="1 0 0 1 0 0"/>
    <Rectangle Self="{image_frame_id}" ItemLayer="layer1" ContentType="GraphicType" GeometricBounds="0 0 {page_height:g} {page_width:g}" StrokeWeight="0" FillColor="Color/$ID/None" StrokeColor="Color/$ID/None">
      <Image Self="{image_id}" Name="{link_name}" ItemLayer="layer1" ItemTransform="1 0 0 1 0 0" ImageTypeName="$ID/Portable Network Graphics (PNG)">
        <Link Self="link{page_number:03d}" LinkResourceURI="Links/{link_name}" LinkResourceFormat="$ID/Portable Network Graphics (PNG)" LinkClassID="35906" LinkClientID="257"/>
      </Image>
    </Rectangle>
    {story_panel}
    {story_frame}
  </Spread>
</idPkg:Spread>
"""


def _story_panel_xml(panel_id: str, bounds: tuple[float, float, float, float], page: dict[str, Any]) -> str:
    top, left, bottom, right = bounds
    page_type = str(page.get("page_type", "story"))
    fill = "Color/Friendly White"
    if page_type == "title_page":
        return ""
    return (
        f'<Rectangle Self="{panel_id}" ContentType="Unassigned" '
        f'ItemLayer="layer1" '
        f'GeometricBounds="{top:g} {left:g} {bottom:g} {right:g}" '
        f'FillColor="{fill}" StrokeColor="Color/Core Crystal" StrokeWeight="1.5"/>'
    )


def _text_frame_xml(text_frame_id: str, story_id: str, bounds: tuple[float, float, float, float]) -> str:
    top, left, bottom, right = bounds
    inset = "8 12 8 12"
    return (
        f'<TextFrame Self="{text_frame_id}" ParentStory="{story_id}" '
        f'ItemLayer="layer1" ContentType="TextType" PreviousTextFrame="n" NextTextFrame="n" '
        f'GeometricBounds="{top:g} {left:g} {bottom:g} {right:g}" '
        f'InsetSpacing="{inset}" StrokeWeight="0" FillColor="Color/$ID/None"/>'
    )


def _text_bounds(page: dict[str, Any], page_width: float, page_height: float) -> tuple[float, float, float, float]:
    page_type = str(page.get("page_type", "story"))
    if page_type == "title_page":
        return 42.0, 54.0, 142.0, page_width - 54.0
    if page_type in {"copyright", "dedication", "activity", "teaser"}:
        return page_height - 160.0, 72.0, page_height - 54.0, page_width - 72.0
    if page_type == "ending":
        return page_height - 150.0, 72.0, page_height - 54.0, page_width - 72.0
    return page_height - 142.0, 72.0, page_height - 54.0, page_width - 72.0


def _story_id(page_number: int) -> str:
    return f"story{page_number:03d}"


def _spread_id(page_number: int) -> str:
    return f"spread{page_number:03d}"
