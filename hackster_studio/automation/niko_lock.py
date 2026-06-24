"""Deterministic Hackster Niko character asset rendering and placement."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter


@dataclass(frozen=True)
class NikoPose:
    name: str
    label: str
    body_lean: int = 0
    head_tilt: int = 0
    antenna_tilt: int = 0
    left_upper_arm: int = 118
    left_forearm: int = 100
    left_hand: int = 0
    right_upper_arm: int = 62
    right_forearm: int = 80
    right_hand: int = 0
    left_thigh: int = 88
    left_shin: int = 94
    left_foot: int = 0
    right_thigh: int = 92
    right_shin: int = 86
    right_foot: int = 0


@dataclass(frozen=True)
class NikoPlacement:
    pose: str
    center_x: float
    base_y: float
    height: float


NIKO_POSES: dict[str, NikoPose] = {
    "stand_front": NikoPose("stand_front", "Standing Front"),
    "walk_front": NikoPose(
        "walk_front", "Walking Front",
        body_lean=-2,
        left_upper_arm=76, left_forearm=96, left_hand=-8,
        right_upper_arm=110, right_forearm=82, right_hand=8,
        left_thigh=78, left_shin=96, left_foot=-5,
        right_thigh=105, right_shin=82, right_foot=4,
    ),
    "point_right": NikoPose(
        "point_right", "Pointing Right",
        body_lean=2, head_tilt=2, antenna_tilt=4,
        left_upper_arm=116, left_forearm=104,
        right_upper_arm=0, right_forearm=0, right_hand=0,
        left_thigh=90, left_shin=92, right_thigh=93, right_shin=88,
    ),
    "kind_wave": NikoPose(
        "kind_wave", "Kind Wave",
        body_lean=-2, head_tilt=-3, antenna_tilt=-8,
        left_upper_arm=118, left_forearm=104,
        right_upper_arm=-58, right_forearm=-92, right_hand=18,
        left_thigh=88, left_shin=94, right_thigh=94, right_shin=86,
    ),
    "thinking": NikoPose(
        "thinking", "Thinking",
        body_lean=-3, head_tilt=-7, antenna_tilt=-10,
        left_upper_arm=116, left_forearm=102,
        right_upper_arm=138, right_forearm=-66, right_hand=-18,
        left_thigh=89, left_shin=93, right_thigh=91, right_shin=87,
    ),
    "celebrate": NikoPose(
        "celebrate", "Celebrate",
        body_lean=0, head_tilt=0, antenna_tilt=0,
        left_upper_arm=-128, left_forearm=-104, left_hand=-10,
        right_upper_arm=-52, right_forearm=-76, right_hand=10,
        left_thigh=82, left_shin=94, left_foot=-4,
        right_thigh=98, right_shin=86, right_foot=4,
    ),
}


DEFAULT_PAGE_PLACEMENTS: dict[int, NikoPlacement] = {
    1: NikoPlacement("walk_front", 0.50, 0.86, 0.64),
    3: NikoPlacement("stand_front", 0.50, 0.82, 0.42),
    4: NikoPlacement("walk_front", 0.42, 0.88, 0.48),
    5: NikoPlacement("thinking", 0.42, 0.88, 0.46),
    6: NikoPlacement("thinking", 0.34, 0.88, 0.42),
    7: NikoPlacement("kind_wave", 0.34, 0.88, 0.42),
    8: NikoPlacement("thinking", 0.34, 0.88, 0.42),
    9: NikoPlacement("point_right", 0.34, 0.88, 0.42),
    10: NikoPlacement("point_right", 0.34, 0.88, 0.42),
    11: NikoPlacement("celebrate", 0.34, 0.88, 0.42),
    12: NikoPlacement("stand_front", 0.30, 0.88, 0.39),
    13: NikoPlacement("point_right", 0.30, 0.88, 0.39),
    14: NikoPlacement("kind_wave", 0.34, 0.88, 0.40),
    15: NikoPlacement("point_right", 0.34, 0.88, 0.40),
    16: NikoPlacement("point_right", 0.30, 0.88, 0.39),
    17: NikoPlacement("stand_front", 0.30, 0.88, 0.39),
    18: NikoPlacement("kind_wave", 0.33, 0.88, 0.40),
    19: NikoPlacement("point_right", 0.36, 0.88, 0.39),
    20: NikoPlacement("point_right", 0.36, 0.88, 0.39),
    21: NikoPlacement("thinking", 0.38, 0.88, 0.40),
    22: NikoPlacement("stand_front", 0.34, 0.88, 0.40),
    23: NikoPlacement("celebrate", 0.42, 0.88, 0.43),
    24: NikoPlacement("kind_wave", 0.35, 0.88, 0.40),
    25: NikoPlacement("stand_front", 0.40, 0.88, 0.42),
    26: NikoPlacement("thinking", 0.34, 0.88, 0.39),
    27: NikoPlacement("celebrate", 0.42, 0.88, 0.42),
    28: NikoPlacement("kind_wave", 0.36, 0.88, 0.40),
    29: NikoPlacement("walk_front", 0.45, 0.88, 0.43),
    30: NikoPlacement("celebrate", 0.43, 0.88, 0.43),
    31: NikoPlacement("point_right", 0.25, 0.82, 0.36),
    32: NikoPlacement("thinking", 0.42, 0.86, 0.42),
}


def placement_for_page(page_number: int) -> NikoPlacement | None:
    return DEFAULT_PAGE_PLACEMENTS.get(page_number)


def render_pose_library(output_dir: Path, *, force: bool = False) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for pose in NIKO_POSES.values():
        path = output_dir / f"niko_{pose.name}.png"
        if path.exists() and not force:
            paths.append(path)
            continue
        render_niko_pose(path, pose)
        paths.append(path)
    return paths


def render_niko_pose(output_path: Path, pose: NikoPose, *, canvas_size: tuple[int, int] = (900, 1100)) -> Path:
    """Render Niko with fixed HN-01 geometry and a transparent background."""
    width, height = canvas_size
    image = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    cx = width // 2
    lean = int(pose.body_lean)
    body_dx = round(lean * 2.4)
    head_dx = round(lean * 4.2)
    head_dy = abs(lean)

    shadow = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse((270, 972, 630, 1046), fill=(0, 0, 0, 84))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))
    draw = ImageDraw.Draw(image)

    hoodie_box = _offset_box((292, 438, 608, 810), body_dx, 0)

    # Backpack stays compact and behind the body; it never extends into a tail.
    _rounded_gradient(image, _offset_box((218, 458, 314, 720), body_dx, 0), 36, (35, 121, 184, 230), (16, 70, 112, 245), outline=(38, 65, 92, 210), width=5)
    _rounded_gradient(image, _offset_box((586, 458, 682, 720), body_dx, 0), 36, (35, 121, 184, 230), (16, 70, 112, 245), outline=(38, 65, 92, 210), width=5)

    _draw_leg(
        image, (376 + body_dx, 760),
        thigh_angle=pose.left_thigh, shin_angle=pose.left_shin, foot_angle=pose.left_foot,
        left=True,
    )
    _draw_leg(
        image, (524 + body_dx, 760),
        thigh_angle=pose.right_thigh, shin_angle=pose.right_shin, foot_angle=pose.right_foot,
        left=False,
    )
    _rounded_gradient(image, hoodie_box, 92, (50, 177, 232, 255), (22, 103, 169, 255), outline=(24, 69, 103, 235), width=7)
    draw.pieslice(_offset_box((286, 392, 614, 594), body_dx, 0), 202, 338, fill=(42, 148, 216, 235))
    draw.line((338 + body_dx, 455, 414 + body_dx, 563), fill=(16, 78, 124, 190), width=7)
    draw.line((562 + body_dx, 455, 486 + body_dx, 563), fill=(16, 78, 124, 190), width=7)
    draw.line((360 + body_dx, 456, 424 + body_dx, 548), fill=(103, 217, 255, 78), width=3)
    draw.line((540 + body_dx, 456, 476 + body_dx, 548), fill=(103, 217, 255, 78), width=3)

    _glow_circle(image, (450 + body_dx, 610), 68, (80, 236, 255, 160), blur=18)
    draw.ellipse(_offset_box((400, 560, 500, 660), body_dx, 0), fill=(69, 218, 245, 255), outline=(223, 255, 255, 245), width=7)
    draw.ellipse(_offset_box((423, 585, 477, 639), body_dx, 0), fill=(196, 255, 255, 245))
    draw.ellipse(_offset_box((420, 578, 448, 608), body_dx, 0), fill=(255, 255, 255, 130))
    draw.arc(_offset_box((320, 480, 580, 770), body_dx, 0), 205, 332, fill=(255, 255, 255, 58), width=5)

    # Front anatomy is composited after the body so pose edits do not hide it.
    _draw_arm(
        image, (306 + body_dx, 512),
        upper_angle=pose.left_upper_arm, forearm_angle=pose.left_forearm, hand_angle=pose.left_hand,
        left=True,
    )
    _draw_arm(
        image, (594 + body_dx, 512),
        upper_angle=pose.right_upper_arm, forearm_angle=pose.right_forearm, hand_angle=pose.right_hand,
        left=False,
    )
    draw = ImageDraw.Draw(image)

    _draw_head_and_antenna(image, pose, cx=cx, head_dx=head_dx, head_dy=head_dy)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.1, percent=115, threshold=5))
    image.save(output_path, dpi=(300, 300))
    return output_path


def _draw_head_and_antenna(canvas: Image.Image, pose: NikoPose, *, cx: int, head_dx: int, head_dy: int) -> None:
    head_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(head_layer)
    head_box = _offset_box((214, 138, 686, 506), head_dx, head_dy)
    face_box = _offset_box((292, 236, 608, 396), head_dx, head_dy)

    _rounded_gradient(head_layer, _offset_box((174, 268, 270, 426), head_dx, head_dy), 42, (47, 83, 122, 255), (12, 25, 42, 255), outline=(24, 41, 62, 245), width=6)
    _rounded_gradient(head_layer, _offset_box((630, 268, 726, 426), head_dx, head_dy), 42, (47, 83, 122, 255), (12, 25, 42, 255), outline=(24, 41, 62, 245), width=6)
    draw.rounded_rectangle(_offset_box((198, 290, 246, 400), head_dx, head_dy), radius=22, fill=(8, 19, 33, 160))
    draw.rounded_rectangle(_offset_box((654, 290, 702, 400), head_dx, head_dy), radius=22, fill=(8, 19, 33, 160))

    _rounded_gradient(head_layer, head_box, 178, (255, 255, 249, 255), (198, 226, 236, 255), outline=(64, 76, 94, 235), width=7)
    draw.arc(_offset_box((238, 160, 662, 348), head_dx, head_dy), 195, 345, fill=(255, 255, 255, 135), width=12)
    draw.arc(_offset_box((244, 392, 656, 506), head_dx, head_dy), 8, 172, fill=(116, 167, 186, 95), width=8)

    _rounded_gradient(head_layer, face_box, 64, (12, 27, 45, 255), (3, 8, 18, 255), outline=(31, 45, 65, 255), width=5)
    draw.arc(_offset_box((316, 248, 584, 334), head_dx, head_dy), 192, 345, fill=(81, 130, 156, 70), width=5)
    _glow_eye(head_layer, (375 + head_dx, 316 + head_dy), 31)
    _glow_eye(head_layer, (525 + head_dx, 316 + head_dy), 31)

    antenna_base = (cx + head_dx, 142 + head_dy)
    antenna_tip = _point_from(antenna_base, -90 + pose.antenna_tilt, 64)
    draw.line((*antenna_base, *antenna_tip), fill=(44, 62, 83, 245), width=9)
    highlight_tip = _point_from((antenna_base[0] + 8, antenna_base[1]), -90 + pose.antenna_tilt, 58)
    draw.line((antenna_base[0] + 8, antenna_base[1], *highlight_tip), fill=(255, 255, 255, 62), width=3)
    _glow_circle(head_layer, antenna_tip, 35, (80, 222, 255, 210), blur=9)
    ax, ay = antenna_tip
    draw.ellipse((ax - 25, ay - 25, ax + 25, ay + 25), fill=(82, 218, 255, 255), outline=(31, 83, 124, 245), width=5)
    draw.ellipse((ax - 10, ay - 16, ax + 10, ay + 4), fill=(230, 255, 255, 200))

    if pose.head_tilt:
        head_layer = head_layer.rotate(
            pose.head_tilt,
            resample=Image.Resampling.BICUBIC,
            center=(cx + head_dx, 322 + head_dy),
        )
    canvas.alpha_composite(head_layer)


def _offset_box(box: tuple[int, int, int, int], dx: int, dy: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (x0 + dx, y0 + dy, x1 + dx, y1 + dy)


def _point_from(origin: tuple[int, int], angle_deg: float, length: float) -> tuple[int, int]:
    radians = math.radians(angle_deg)
    return (
        round(origin[0] + math.cos(radians) * length),
        round(origin[1] + math.sin(radians) * length),
    )


def _rounded_gradient(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    top: tuple[int, int, int, int],
    bottom: tuple[int, int, int, int],
    *,
    outline: tuple[int, int, int, int] | None = None,
    width: int = 1,
) -> None:
    x0, y0, x1, y1 = box
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    gradient = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gpx = gradient.load()
    for y in range(h):
        t = y / max(1, h - 1)
        row = tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(4))
        for x in range(w):
            gpx[x, y] = row
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    canvas.paste(gradient, (x0, y0), mask)
    draw = ImageDraw.Draw(canvas)
    if outline:
        draw.rounded_rectangle(box, radius=radius, outline=outline, width=width)


def _glow_circle(canvas: Image.Image, center: tuple[int, int], radius: int, color: tuple[int, int, int, int], *, blur: int) -> None:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _glow_eye(canvas: Image.Image, center: tuple[int, int], radius: int) -> None:
    _glow_circle(canvas, center, radius + 18, (65, 231, 255, 125), blur=12)
    draw = ImageDraw.Draw(canvas)
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(80, 236, 255, 255))
    draw.ellipse((x - radius + 8, y - radius + 8, x + radius - 8, y + radius - 8), fill=(223, 255, 255, 255))
    draw.ellipse((x - 8, y - 14, x + 8, y + 2), fill=(255, 255, 255, 230))


def _draw_limb_path(
    canvas: Image.Image,
    points: tuple[int, ...],
    *,
    fill: tuple[int, int, int, int],
    highlight: tuple[int, int, int, int],
    outline: tuple[int, int, int, int],
    width: int,
) -> None:
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.line(points, fill=(0, 0, 0, 55), width=width + 10, joint="curve")
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)))
    draw = ImageDraw.Draw(canvas)
    draw.line(points, fill=outline, width=width + 10, joint="curve")
    draw.line(points, fill=fill, width=width, joint="curve")
    draw.line(points, fill=highlight, width=max(4, width // 7), joint="curve")


def _draw_arm(
    canvas: Image.Image,
    shoulder: tuple[int, int],
    *,
    upper_angle: int,
    forearm_angle: int,
    hand_angle: int,
    left: bool,
) -> None:
    elbow = _point_from(shoulder, upper_angle, 152)
    wrist = _point_from(elbow, forearm_angle, 122)
    hand_center = _point_from(wrist, forearm_angle + hand_angle, 26)
    points = (*shoulder, *elbow, *wrist)
    _draw_limb_path(
        canvas,
        points,
        fill=(35, 139, 199, 255),
        highlight=(116, 224, 255, 150),
        outline=(18, 61, 95, 235),
        width=48,
    )
    draw = ImageDraw.Draw(canvas)
    hx, hy = hand_center
    draw.rounded_rectangle((hx - 34, hy - 28, hx + 34, hy + 38), radius=24, fill=(239, 250, 255, 255), outline=(39, 61, 84, 245), width=6)
    draw.arc((hx - 20, hy - 12, hx + 20, hy + 28), 20, 158, fill=(128, 164, 181, 115), width=3)


def _draw_leg(
    canvas: Image.Image,
    hip: tuple[int, int],
    *,
    thigh_angle: int,
    shin_angle: int,
    foot_angle: int,
    left: bool,
) -> None:
    knee = _point_from(hip, thigh_angle, 132)
    ankle = _point_from(knee, shin_angle, 142)
    toe = _point_from(ankle, foot_angle, 42)
    _draw_limb_path(
        canvas,
        (*hip, *knee, *ankle),
        fill=(222, 239, 249, 255),
        highlight=(255, 255, 255, 145),
        outline=(48, 72, 97, 235),
        width=60,
    )
    draw = ImageDraw.Draw(canvas)
    foot_x, foot_y = toe
    shoe = (foot_x - 60, foot_y - 12, foot_x + 70, foot_y + 54)
    _rounded_gradient(canvas, shoe, 28, (255, 255, 255, 255), (197, 222, 236, 255), outline=(37, 60, 86, 245), width=7)
    draw.line((foot_x - 32, foot_y + 24, foot_x + 44, foot_y + 24), fill=(119, 155, 176, 90), width=3)


def write_lock_manifest(output_path: Path, *, book_pages: list[dict[str, Any]]) -> Path:
    lines = [
        "# Niko Character Lock Manifest",
        "",
        "Niko is no longer generated inside the background art. Background images should leave room for Niko, and the Niko pose PNG is loaded as a separate editable Story Maker character layer.",
        "",
        "| Page | Pose | Center X | Base Y | Height |",
        "| --- | --- | --- | --- | --- |",
    ]
    for page in book_pages:
        page_number = int(page["page_number"])
        placement = placement_for_page(page_number)
        if not placement:
            continue
        lines.append(
            f"| {page_number:03d} | {placement.pose} | {placement.center_x:.2f} | {placement.base_y:.2f} | {placement.height:.2f} |"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def page_fields_for_niko_lock(page_number: int, *, mode: str = "posable_layer") -> dict[str, Any]:
    placement = placement_for_page(page_number)
    if not placement:
        return {}
    return {
        "niko_layer_mode": mode,
        "niko_pose": placement.pose,
        "niko_center_x": placement.center_x,
        "niko_base_y": placement.base_y,
        "niko_height": placement.height,
    }
