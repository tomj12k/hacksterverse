# Story Maker — Full Design Spec
*2026-06-20*

---

## 1. What We're Building

A layered 2D storybook compositor built into the existing FastAPI/Jinja2 dashboard. Each book page becomes an editable scene graph: background plate, midground elements, props, character cutouts, foreground overlaps, a lighting overlay, a camera viewport, and draft text — all composited in the browser and exported as a print-ready flat PNG.

The compositor is a self-contained JS page (`/story-maker`) that talks to FastAPI via REST. Scene data is owned by a scene JSON schema we control; Konva.js renders from it but does not define it. All other dashboard pages (characters, books, prompts) remain Jinja2 server-rendered and are untouched.

---

## 2. Existing Prototype Inventory

Already working — **do not rewrite**:

| Piece | File | What it does |
|---|---|---|
| Scene load service | `hackster_studio/services/story_maker.py` | Loads/creates scene JSON from `storybook_scenes/` |
| Story maker route | `hackster_studio/main.py:221` | `GET /story-maker` serves the compositor page |
| Asset serve route | `hackster_studio/main.py:231` | `GET /project-assets/{path}` serves any project file |
| Three-panel layout | `hackster_studio/templates/story_maker.html` | Layers panel · Stage · Inspector |
| Compositor JS | `hackster_studio/static/app.js` | Drag-to-position, layer selection, inspector controls, bone list |
| ComfyUI engine | `hackster_studio/automation/comfyui_engine.py` | `generate_image_comfyui()` — submit prompt, poll, save PNG |

Normalized 0–1 coordinates for `x/y/width/height` are established and correct — keep them.

---

## 3. Scene Schema

Scene files live at `storybook_scenes/{book_slug}/page_{number:03d}.scene.json`.

### Top-level

```json
{
  "book_slug": "book01_password_dragon",
  "page_number": 4,
  "canvas": {
    "trim_inches": [8.5, 8.5],
    "bleed_inches": 0.125,
    "safe_margin_inches": 0.5,
    "dpi": 300,
    "width_px": 2625,
    "height_px": 2625
  },
  "lighting_brief": "warm_sunset_left",
  "layers": [ ... ]
}
```

`lighting_brief` is the scene-level lighting intent. Every generated asset should match it. Valid values: `ambient_soft`, `warm_sunset_left`, `cool_forest_ambient`, `dramatic_backlight`.

### Layer types

All layers share: `id` (string), `name` (string), `type` (string), `z_index` (int).

**`background`**
```json
{
  "id": "bg_001", "name": "Cyber Forest Sky", "type": "background", "z_index": 0,
  "parallax_factor": 0.1,
  "asset_path": "assets/layers/backgrounds/cyber_forest_warm_sunset_left.png",
  "lighting_variant": "warm_sunset_left",
  "transform": { "x": 0.0, "y": 0.0, "width": 1.5, "height": 1.5, "scale": 1.0, "rotation": 0, "opacity": 1 }
}
```
Generated at 1.5× canvas size to give the camera room to pan.

**`midground`**
```json
{
  "id": "mid_001", "name": "Crystal Caves Trees", "type": "midground", "z_index": 2,
  "parallax_factor": 0.4,
  "asset_path": "assets/layers/midground/cyber_trees_warm_sunset_left.png",
  "transform": { "x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "scale": 1.0, "rotation": 0, "opacity": 1 }
}
```

**`character`**
```json
{
  "id": "char_niko", "name": "Hackster Niko", "type": "character", "z_index": 3,
  "parallax_factor": 1.0,
  "character_slug": "niko",
  "asset_path": "assets/layers/characters/niko/pointing_right_warm_sunset_left.png",
  "lighting_variant": "warm_sunset_left",
  "pose": "pointing_right",
  "rig": null,
  "shadow": { "enabled": true, "angle": 225, "distance": 18, "blur": 12, "opacity": 0.35 },
  "transform": { "x": 0.45, "y": 0.6, "width": 0.2, "height": 0.4, "scale": 1.0, "rotation": 0, "opacity": 1 }
}
```
`rig: null` now. When skeleton rigging is built, `rig` will contain a bone-transform tree (see §9). The field exists from day one so future scenes don't require schema migration.

**`props`**
```json
{
  "id": "prop_vault", "name": "Password Vault", "type": "props", "z_index": 4,
  "parallax_factor": 1.0,
  "asset_path": "assets/layers/props/password_vault_warm_sunset_left.png",
  "lighting_variant": "warm_sunset_left",
  "shadow": { "enabled": true, "angle": 225, "distance": 10, "blur": 8, "opacity": 0.25 },
  "transform": { "x": 0.7, "y": 0.65, "width": 0.15, "height": 0.15, "scale": 1.0, "rotation": 0, "opacity": 1 }
}
```

**`foreground`**
```json
{
  "id": "fg_001", "name": "Foreground Branches", "type": "foreground", "z_index": 8,
  "parallax_factor": 1.5,
  "asset_path": "assets/layers/foreground/cyber_branches_left.png",
  "transform": { "x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "scale": 1.0, "rotation": 0, "opacity": 1 }
}
```
Parallax factor > 1.0 means it moves faster than characters on camera pan — reads as closer.

**`lighting`**
```json
{
  "id": "lighting_001", "name": "Warm Sunset", "type": "lighting", "z_index": 10,
  "tint_color": "#FF8C42",
  "blend_mode": "multiply",
  "opacity": 0.22
}
```
Rendered as a full-canvas rectangle with CSS `mix-blend-mode`. No `transform` or `asset_path`.

**`text`** (draft preview only — never exported in flat PNG)
```json
{
  "id": "text_001", "name": "Story Text", "type": "text", "z_index": 20,
  "text": "Niko stepped into the glowing forest...",
  "font_size": 0.04,
  "transform": { "x": 0.1, "y": 0.75, "width": 0.8, "height": 0.2, "opacity": 1 }
}
```
`font_size` is normalized (fraction of canvas height).

**`camera`**
```json
{
  "id": "camera_001", "name": "Camera", "type": "camera", "z_index": 99,
  "transform": { "x": 0.0, "y": 0.0, "zoom": 1.0, "rotation": 0 }
}
```
Lives in the layers array so it's visible in the layer panel. Selecting it shows crop handles on the stage. Moving it shifts all other layers by their `parallax_factor`. On export, the camera's crop window defines the output boundary.

### Layer panel order (top → bottom)

Camera · Lighting · Text · Foreground · Characters · Props · Midground · Background

`z_index` drives render order. The panel lists layers from highest to lowest z_index.

---

## 4. Asset Library

File-system based. No new SQLite table — paths are stable once generated.

```
assets/layers/
  backgrounds/
    {environment_slug}_{lighting_variant}.png     # 1.5× canvas (3938×3938px at 300 DPI)
  midground/
    {environment_slug}_{subject}_{lighting_variant}.png
  foreground/
    {environment_slug}_{subject}_{lighting_variant}.png
  characters/
    {character_slug}/
      poses.json                                  # pose manifest (see below)
      {pose_id}_{lighting_variant}.png            # transparent PNG cutout
  props/
    {prop_slug}_{lighting_variant}.png            # transparent PNG cutout
  hidden_objects/
    golden_gear.png
    tiny_bug.png
    blue_crystal.png
    mini_robot.png
```

### Pose manifest (`poses.json`)

```json
{
  "character": "niko",
  "poses": [
    { "id": "standing_neutral", "label": "Standing Neutral", "tags": ["idle"] },
    { "id": "pointing_right",   "label": "Pointing Right",   "tags": ["teaching", "action"] },
    { "id": "crouching",        "label": "Crouching",        "tags": ["action"] },
    { "id": "waving",           "label": "Waving",           "tags": ["greeting"] },
    { "id": "comforting",       "label": "Comforting",       "tags": ["emotion"] },
    { "id": "celebrating",      "label": "Celebrating",      "tags": ["emotion", "action"] },
    { "id": "thinking",         "label": "Thinking",         "tags": ["idle", "teaching"] },
    { "id": "running",          "label": "Running",          "tags": ["action"] }
  ]
}
```

The compositor reads `poses.json` to populate the pose picker in the inspector when a `character` layer is selected.

### Lighting variants

| Variant ID | Shadow angle | Description |
|---|---|---|
| `ambient_soft` | 270° (straight down) | Overcast, even, no drama |
| `warm_sunset_left` | 225° | Golden hour from camera left |
| `cool_forest_ambient` | 270° | Cool green-tinted dappled light |
| `dramatic_backlight` | 45° | Strong backlight, rim-lit characters |

When `scene.lighting_brief` is set, the inspector auto-fills the shadow angle for any character or prop layer to the matching value above. The user can override.

---

## 5. API Endpoints

All new routes live under `/api/` prefix. Existing routes are unchanged.

### Scenes

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/scenes/{book_slug}/{page}` | Return scene JSON |
| `PUT` | `/api/scenes/{book_slug}/{page}` | Save scene JSON to disk |

`PUT` body: the full scene JSON object. Validates required fields (`book_slug`, `page_number`, `layers`). Writes to `storybook_scenes/{book_slug}/page_{page:03d}.scene.json`.

### Assets

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/assets` | List all available assets by type |
| `GET` | `/api/assets/characters/{character_slug}/poses` | Return that character's `poses.json` |

`GET /api/assets` response:
```json
{
  "backgrounds": ["assets/layers/backgrounds/cyber_forest_warm_sunset_left.png"],
  "characters": {
    "niko": ["assets/layers/characters/niko/pointing_right_warm_sunset_left.png"]
  },
  "props": ["assets/layers/props/password_vault_warm_sunset_left.png"]
}
```
Built by scanning `assets/layers/` — no database needed.

### Generation

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/generate` | Submit a ComfyUI generation job |
| `GET` | `/api/generate/{job_id}` | Poll job status |

`POST /api/generate` body:
```json
{
  "layer_id": "char_niko",
  "layer_type": "character",
  "prompt": "Hackster Niko pointing right...",
  "output_path": "assets/layers/characters/niko/pointing_right_warm_sunset_left.png",
  "lighting_variant": "warm_sunset_left"
}
```

Returns: `{ "job_id": "uuid4" }`. The server enqueues the job via FastAPI `BackgroundTasks`, which runs `generate_image_comfyui()` in a thread pool. Job status is stored in a module-level `dict[str, JobStatus]` keyed by `job_id`. Jobs are ephemeral — status is lost on server restart, which is acceptable for an interactive local tool.

`GET /api/generate/{job_id}` returns:
```json
{ "status": "pending|running|done|failed", "asset_path": "..." }
```
On `done`, `asset_path` is the saved file path the compositor can immediately use.

### Export

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/export/{book_slug}/{page}` | Compose and export page |

Query param `mode`: `flat` (no text, for Affinity hand-off) or `draft` (text baked in, for quick review).

Output paths:
- `data/generated/pages/{book_slug}/page_{page:03d}_flat.png`
- `data/generated/pages/{book_slug}/page_{page:03d}_draft.png`

Returns: `{ "output_path": "..." }` on success.

---

## 6. Compositor UI Changes

The existing three-panel layout and drag/inspector/bone-list logic stays. These changes extend it:

### Layer panel additions

- Layer type icon prefix (🎥 camera, 💡 lighting, 🌄 bg, 🌿 mid, 🌳 fg, 🧑 character, 📦 props, 📝 text)
- "Add layer" button opens an asset browser modal
- Reorder layers via drag handles (updates `z_index`)
- Delete layer button (× on hover)

### Stage additions

- **Camera layer selected**: draw a dashed crop-rect overlay on the stage; dragging the rect pans `camera.transform.x/y`; scroll zooms `camera.transform.zoom`
- **Lighting layer**: render as a full-stage `<div>` with `mix-blend-mode` and background color; no image
- **Shadow on character/prop**: CSS `filter: drop-shadow(...)` computed from `layer.shadow`
- **Parallax preview**: when camera transform changes, recompute each layer's rendered position as `layer.transform.x - camera.transform.x * layer.parallax_factor`
- **Text layer**: render as a semi-transparent positioned `<div>` with the story text; toggle visibility with an eye icon

### Inspector additions

- **Character layer selected**: show pose picker (grid of thumbnail poses from `poses.json`); clicking a pose updates `layer.pose` and `layer.asset_path`
- **Character/prop layer selected**: show shadow controls (enabled toggle, angle, distance, blur, opacity)
- **Lighting layer selected**: show tint color picker, blend mode selector, opacity
- **Camera layer selected**: show zoom, rotation; x/y shown as offset in the existing controls
- **Generate button**: available when a layer has enough context (type + scene lighting brief); opens a prompt editor pre-filled from the scene, submits to `POST /api/generate`, polls until done, then hot-swaps the layer image without a page reload

### Toolbar (new, above stage)

- **Save** → `PUT /api/scenes/{slug}/{page}`; shows "Saved ✓" confirmation
- **Export flat** → `POST /api/export?mode=flat`
- **Export draft** → `POST /api/export?mode=draft`
- **Toggle text** → show/hide text layers in the stage preview

### Asset browser modal

Opens on "Add layer". Tabs: Backgrounds · Midground · Foreground · Characters · Props. Hidden objects (Golden Gear, Tiny Bug, Blue Crystal, Mini Robot) live under the Props tab — they are small transparent PNGs stored in `assets/layers/hidden_objects/` and become `props` layers when added. Clicking any asset creates a new layer of the correct type and appends it to `scene.layers`.

---

## 7. Export Pipeline

Server-side Pillow composition in a new `hackster_studio/services/exporter.py`.

Steps:
1. Load scene JSON
2. Sort layers by `z_index` ascending
3. Open canvas: `Image.new("RGBA", (canvas.width_px, canvas.height_px))`
4. For each layer except `camera` and (in flat mode) `text`:
   - Load `asset_path` as RGBA image
   - Apply `transform`: scale, rotate, position (denormalize coords to pixels)
   - Apply `shadow` if present: pre-composite a blurred dark copy offset by angle/distance
   - For `lighting` layer: generate a solid RGBA rect at `tint_color` and composite with the matching Pillow blend op
   - Alpha-composite onto canvas
5. Apply camera crop: crop canvas to the viewport defined by `camera.transform`
6. Resize to 2625×2625 if camera zoom altered size
7. Save as PNG with DPI metadata (reuse `set_dpi_metadata()` from `comfyui_engine.py`)

Lighting blend modes supported: `multiply` (`ImageChops.multiply`) and `screen` (`ImageChops.screen`). Overlay requires manual per-pixel math and is deferred — not supported in this version.

---

## 8. Database Changes

None. Scenes are JSON files on disk. Generation job state is an in-memory `dict[str, JobStatus]` in the API module — jobs are ephemeral and don't need to survive a server restart.

---

## 9. Skeleton Rig — Future Schema (reserved, not built now)

When skeleton rigging is implemented, `layer.rig` will look like:

```json
{
  "rig": {
    "sprite_parts": {
      "head":       "assets/layers/characters/niko/parts/head.png",
      "torso":      "assets/layers/characters/niko/parts/torso.png",
      "upper_arm_l": "assets/layers/characters/niko/parts/upper_arm_l.png"
    },
    "bones": [
      { "id": "root",        "parent": null,   "x": 0.5,  "y": 0.9,  "rotation": 0 },
      { "id": "torso",       "parent": "root", "x": 0.5,  "y": 0.7,  "rotation": 0 },
      { "id": "head",        "parent": "torso","x": 0.5,  "y": 0.45, "rotation": 0 },
      { "id": "upper_arm_l", "parent": "torso","x": 0.38, "y": 0.6,  "rotation": -30 }
    ]
  }
}
```

The existing bone list inspector in `app.js` already reads `layer.rig.bones` — it will work without changes when real rig data arrives.

---

## 10. Out of Scope (this version)

- Full skeleton mesh deform / per-pixel warp
- CMYK color space export (Affinity handles that)
- Direct Affinity Publisher integration (flat PNG hand-off is the boundary)
- Multi-page scene batch export (export is per-page)
- Undo/redo history (save manually; browser back does not restore canvas state)
- Real-time multiplayer / collaborative editing
- Video/animation export (covered by the existing movie pipeline)
