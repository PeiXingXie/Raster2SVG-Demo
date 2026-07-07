"""Generate shape-based Raster to SVG application icons."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "desktop" / "assets"


def rounded_rectangle(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def make_icon(size: int = 1024) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Quiet dark base with enough contrast for Windows taskbar and installer surfaces.
    rounded_rectangle(
        draw,
        (64, 64, size - 64, size - 64),
        radius=168,
        fill=(22, 30, 39, 255),
        outline=(234, 241, 248, 32),
        width=10,
    )

    # Raster pixels on the left.
    pixel = 76
    gap = 16
    start_x = 154
    start_y = 238
    colors = [
        (244, 112, 82, 255),
        (255, 194, 87, 255),
        (77, 191, 157, 255),
        (64, 143, 255, 255),
        (235, 238, 244, 255),
    ]
    grid = [
        [0, 1, 4],
        [4, 2, 3],
        [3, 4, 2],
    ]
    for row, values in enumerate(grid):
        for col, color_index in enumerate(values):
            x0 = start_x + col * (pixel + gap)
            y0 = start_y + row * (pixel + gap)
            rounded_rectangle(
                draw,
                (x0, y0, x0 + pixel, y0 + pixel),
                radius=18,
                fill=colors[color_index],
            )

    # Transitional shapes: pixels progressively turn into editable primitives.
    transition_x = 458
    transition_y = 254
    draw.polygon(
        [(transition_x + 42, transition_y), (transition_x + 100, transition_y + 98), (transition_x - 16, transition_y + 98)],
        fill=(255, 194, 87, 255),
    )
    draw.ellipse(
        (transition_x + 6, transition_y + 132, transition_x + 108, transition_y + 234),
        fill=(77, 191, 157, 255),
    )
    rounded_rectangle(
        draw,
        (transition_x - 4, transition_y + 268, transition_x + 112, transition_y + 344),
        radius=38,
        fill=(64, 143, 255, 255),
    )
    for x, y in [(transition_x + 42, transition_y), (transition_x + 100, transition_y + 98), (transition_x - 16, transition_y + 98)]:
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(235, 238, 244, 245))

    # Arrow bridge: raster to editable shapes.
    draw.line((386, 512, 466, 512), fill=(235, 238, 244, 210), width=18)
    draw.polygon(
        [(466, 512), (434, 482), (434, 542)],
        fill=(235, 238, 244, 230),
    )

    # Vector path on the right: nodes and clean shape outlines.
    path_points = [
        (604, 710),
        (672, 448),
        (846, 304),
        (812, 700),
    ]
    draw.line(path_points, fill=(235, 238, 244, 255), width=34, joint="curve")
    draw.line(path_points, fill=(64, 143, 255, 255), width=16, joint="curve")

    for x, y, radius, color in [
        (604, 710, 48, (77, 191, 157, 255)),
        (672, 448, 42, (255, 194, 87, 255)),
        (846, 304, 50, (244, 112, 82, 255)),
        (812, 700, 46, (64, 143, 255, 255)),
    ]:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        draw.ellipse(
            (x - radius + 11, y - radius + 11, x + radius - 11, y + radius - 11),
            outline=(22, 30, 39, 180),
            width=8,
        )
    draw.polygon([(754, 392), (826, 450), (742, 494)], outline=(235, 238, 244, 245), fill=None)
    draw.rectangle((700, 582, 780, 662), outline=(235, 238, 244, 245), width=12)

    return image


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    icon = make_icon()
    icon.save(ASSET_DIR / "icon.png")
    icon.save(
        ASSET_DIR / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
