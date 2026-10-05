from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from anki_imagegen.config import load_config
from anki_imagegen.generator import Generator, load_mflux_model

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.slow
def test_real_model_makes_a_png():
    config = PROJECT_ROOT / "config.toml"
    settings = load_config(config if config.exists() else PROJECT_ROOT / "config.example.toml").generator
    generator = Generator(settings, load_mflux_model)
    # The MCP server runs each tool call on a pool thread: load on one thread, generate on another.
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(generator.generate, "a pear, flat vector illustration", 256, 256, 1).result()
    png = generator.generate("a red apple, flat vector illustration, white background", 256, 256, seed=1)
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    (PROJECT_ROOT / "output").mkdir(exist_ok=True)
    (PROJECT_ROOT / "output" / "smoke.png").write_bytes(png)
