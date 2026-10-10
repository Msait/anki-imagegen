import io

import pytest
from PIL import Image

from anki_imagegen.caption import draw_caption, layout_lines


def blank_png(size: int = 768, color=(40, 90, 160)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


def open_png(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def is_banner_yellow(pixel) -> bool:
    r, g, b = pixel
    return r > 200 and g > 170 and b < 90


def test_banner_drawn_at_bottom_and_top_untouched():
    original = open_png(blank_png())
    result = open_png(draw_caption(blank_png(), "HANDICAP"))
    assert result.size == original.size
    top = result.crop((0, 0, 768, 500))
    assert top.tobytes() == original.crop((0, 0, 768, 500)).tobytes()
    bottom = result.crop((0, 600, 768, 768))
    pixels = list(bottom.get_flattened_data())
    yellow = sum(is_banner_yellow(p) for p in pixels)
    dark = sum(max(p) < 60 for p in pixels)
    assert yellow > len(pixels) * 0.3  # the banner
    assert dark > len(pixels) * 0.02  # the text on it


def test_same_text_gives_same_image():
    assert draw_caption(blank_png(), "RICKETY") == draw_caption(blank_png(), "RICKETY")


def test_short_text_stays_on_one_line():
    assert layout_lines("PUNGENT", 768) == ["PUNGENT"]


def test_long_text_wraps_to_two_lines_at_a_space():
    lines = layout_lines("GIVE SB A (QUICK) RUNDOWN (OF STH)", 768)
    assert len(lines) == 2
    assert " ".join(lines) == "GIVE SB A (QUICK) RUNDOWN (OF STH)"


def test_long_text_fits_inside_the_image():
    result = open_png(draw_caption(blank_png(), "LANGUISH BENEATH THE HOT SUN"))
    # the banner leaves a margin on both sides, so the edge columns keep the scene color
    for x in (0, 767):
        column = [result.getpixel((x, y)) for y in range(600, 768)]
        assert not any(is_banner_yellow(p) for p in column)


def test_empty_text_rejected():
    with pytest.raises(ValueError, match="caption"):
        draw_caption(blank_png(), "   ")
