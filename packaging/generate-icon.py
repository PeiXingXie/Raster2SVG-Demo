"""Generate production desktop icons from the selected Shape Studio artwork."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "desktop" / "assets"
STATIC_ICON_DIR = ROOT / "src" / "deepagents_template" / "static" / "assets" / "icon"
SOURCE_ICON = ASSET_DIR / "icon-source.png"

ICON_SIZE = 1024
SOURCE_CROP_LEFT = 155
SOURCE_CROP_TOP = 150
SOURCE_CROP_RIGHT = 145
SOURCE_CROP_BOTTOM = 150


def _rounded_tile_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((18, 18, size - 18, size - 18), radius=148, fill=255)
    return mask


def _foreground_mask(image: Image.Image) -> Image.Image:
    """Keep the artwork and local shadows while dropping the source border."""
    rgba = image.convert("RGBA")
    mask = Image.new("L", rgba.size, 0)
    src = rgba.load()
    out = mask.load()

    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = src[x, y]
            if a == 0:
                continue
            high = max(r, g, b)
            low = min(r, g, b)
            saturation = high - low
            brightness = (r + g + b) / 3
            if saturation > 35 or brightness < 205:
                out[x, y] = 255

    return mask.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(2.5))


def _clean_background(image: Image.Image) -> Image.Image:
    """Place the artwork on a clean borderless background."""
    base = image.convert("RGBA")
    size = base.width

    background = Image.new("RGBA", base.size, (238, 247, 255, 255))
    background.putalpha(_rounded_tile_mask(size))

    foreground = Image.new("RGBA", base.size, (0, 0, 0, 0))
    foreground.alpha_composite(base)
    foreground.putalpha(ImageChops.multiply(base.getchannel("A"), _foreground_mask(base)))

    return Image.alpha_composite(background, foreground)


def _transparent_foreground(image: Image.Image) -> Image.Image:
    foreground = Image.new("RGBA", image.size, (0, 0, 0, 0))
    foreground.alpha_composite(image.convert("RGBA"))
    foreground.putalpha(ImageChops.multiply(foreground.getchannel("A"), _foreground_mask(foreground)))
    return foreground


def _resize_and_center(source: Image.Image, size: int) -> Image.Image:
    w, h = source.size
    crop = source.crop(
        (
            SOURCE_CROP_LEFT,
            SOURCE_CROP_TOP,
            w - SOURCE_CROP_RIGHT,
            h - SOURCE_CROP_BOTTOM,
        )
    )
    resized = crop.resize((size, size), Image.Resampling.LANCZOS)

    # The source is square and opaque. This mask keeps the icon in a standard
    # rounded-square silhouette even if upstream artwork changes slightly.
    mask = _rounded_tile_mask(size)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(resized)
    canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"), mask))
    return canvas


def make_icon(size: int = ICON_SIZE) -> Image.Image:
    if not SOURCE_ICON.exists():
        raise FileNotFoundError(f"Missing source icon artwork: {SOURCE_ICON}")

    source = Image.open(SOURCE_ICON).convert("RGBA")
    icon = _resize_and_center(source, size)
    return _clean_background(icon)


def make_transparent_icon(size: int = ICON_SIZE) -> Image.Image:
    if not SOURCE_ICON.exists():
        raise FileNotFoundError(f"Missing source icon artwork: {SOURCE_ICON}")

    source = Image.open(SOURCE_ICON).convert("RGBA")
    icon = _resize_and_center(source, size)
    return _transparent_foreground(icon)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_ICON_DIR.mkdir(parents=True, exist_ok=True)
    icon = make_icon()
    transparent_icon = make_transparent_icon()
    icon.save(ASSET_DIR / "icon.png")
    transparent_icon.save(STATIC_ICON_DIR / "icon-transparent.png")
    icon.save(
        ASSET_DIR / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
