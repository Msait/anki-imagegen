"""Draw a caption onto a generated image as a yellow brush-stroke banner.

The image model misspells rare words ("HANDICAP" comes out as "HANDHCAP"), so the
caption is set in a real font after generation instead of being part of the prompt.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
BANNER_RGB = (247, 212, 32)
TEXT_RGB = (20, 20, 20)

# Proportions of the image width.
EDGE_MARGIN = 0.04  # the banner never touches the image edge
BOTTOM_MARGIN = 0.035
MAX_LINE_WIDTH = 0.80
MAX_FONT = 0.085
MIN_ONE_LINE_FONT = 0.055  # a caption that would need a smaller font wraps to two lines

# Proportions of the font size.
PAD_X = 0.8
PAD_Y = 0.45
LINE_HEIGHT = 1.15
EDGE_JITTER = 0.07  # roughness of the brush stroke's long edges


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _fit_size(lines: list[str], width: int) -> int:
    """Largest font size (up to MAX_FONT) at which every line fits MAX_LINE_WIDTH."""
    size = round(width * MAX_FONT)
    longest = max(_font(size).getlength(line) for line in lines)
    limit = width * MAX_LINE_WIDTH
    return size if longest <= limit else int(size * limit / longest)


def _layout(text: str, width: int) -> tuple[list[str], int]:
    lines = [text]
    size = _fit_size(lines, width)
    words = text.split(" ")
    if size < width * MIN_ONE_LINE_FONT and len(words) > 1:
        # split at the space that balances the two lines best
        cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
        size = _fit_size(lines, width)
    return lines, size


def layout_lines(text: str, width: int) -> list[str]:
    """How a caption is split into lines on an image of this width."""
    return _layout(text, width)[0]


def _brush_polygon(
    rng: random.Random, left: float, top: float, right: float, bottom: float, size: int
) -> list[tuple[float, float]]:
    jitter = size * EDGE_JITTER
    step = max(size // 3, 4)
    top_edge = [(x, top + rng.uniform(-jitter, jitter)) for x in range(round(left), round(right), step)]
    bottom_edge = [(x, bottom + rng.uniform(-jitter, jitter)) for x in range(round(right), round(left), -step)]
    # ragged brush ends: the stroke starts and stops unevenly
    end_points = 5
    right_end = [
        (right - rng.uniform(0, size * 0.35), top + (bottom - top) * i / end_points) for i in range(end_points + 1)
    ]
    left_end = [
        (left + rng.uniform(0, size * 0.35), bottom - (bottom - top) * i / end_points) for i in range(end_points + 1)
    ]
    return top_edge + right_end + bottom_edge + left_end


def draw_caption(png: bytes, text: str) -> bytes:
    """Return png with text on a banner at the bottom center."""
    text = " ".join(text.split())
    if not text:
        raise ValueError("caption must not be blank")
    image = Image.open(io.BytesIO(png)).convert("RGB")
    width, height = image.size
    lines, size = _layout(text, width)
    font = _font(size)

    line_height = size * LINE_HEIGHT
    banner_w = min(max(font.getlength(line) for line in lines) + 2 * size * PAD_X, width * (1 - 2 * EDGE_MARGIN))
    banner_h = len(lines) * line_height + 2 * size * PAD_Y
    left = (width - banner_w) / 2
    bottom = height - width * BOTTOM_MARGIN
    top = bottom - banner_h

    rng = random.Random(text)  # same caption, same brush stroke
    draw = ImageDraw.Draw(image)
    draw.polygon(_brush_polygon(rng, left, top, left + banner_w, bottom, size), fill=BANNER_RGB)
    center_x = width / 2
    first_y = top + size * PAD_Y + line_height / 2
    for i, line in enumerate(lines):
        draw.text((center_x, first_y + i * line_height), line, font=font, fill=TEXT_RGB, anchor="mm")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
