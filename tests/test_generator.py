import threading
from pathlib import Path

import pytest

from anki_imagegen.config import GeneratorSettings
from anki_imagegen.generator import GenerationError, Generator, ensure_disk_space
from anki_imagegen.models import ModelSpec

SETTINGS = GeneratorSettings(model="z-image-turbo", quantize=4, steps=9, width=512, height=512)
GB = 10**9


class FakeModel:
    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def generate_png(self, **kwargs) -> bytes:
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail
        return b"\x89PNG fake"


class CountingLoader:
    def __init__(self, model: FakeModel) -> None:
        self.model = model
        self.loads = 0

    def __call__(self, settings: GeneratorSettings) -> FakeModel:
        self.loads += 1
        return self.model


def make(tmp_path: Path, model: FakeModel | None = None, free_gb: float = 100):
    loader = CountingLoader(model or FakeModel())
    gen = Generator(SETTINGS, loader, cache_dir=tmp_path, free_bytes=lambda p: int(free_gb * GB))
    return gen, loader


def test_uses_defaults_and_loads_once(tmp_path):
    gen, loader = make(tmp_path)
    assert gen.generate("an apple") == b"\x89PNG fake"
    gen.generate("a pear", width=768, height=256, seed=7)
    assert loader.loads == 1
    first, second = loader.model.calls
    assert (first["width"], first["height"], first["steps"]) == (512, 512, 9)
    assert second == {"prompt": "a pear", "width": 768, "height": 256, "steps": 9, "seed": 7}


def test_does_not_load_model_at_construction(tmp_path):
    _, loader = make(tmp_path)
    assert loader.loads == 0


@pytest.mark.parametrize(
    ("prompt", "width", "height", "match"),
    [("   ", None, None, "prompt"), ("x", 500, None, "width"), ("x", None, 2048, "height")],
)
def test_resolve_request_rejects(tmp_path, prompt, width, height, match):
    gen, loader = make(tmp_path)
    with pytest.raises(ValueError, match=match):
        gen.generate(prompt, width, height)
    assert loader.loads == 0


def test_resolve_request_strips_prompt(tmp_path):
    gen, _ = make(tmp_path)
    assert gen.resolve_request("  an apple \n", None, None) == ("an apple", 512, 512)


def test_model_failure_becomes_generation_error(tmp_path):
    gen, _ = make(tmp_path, FakeModel(fail=MemoryError("out of memory")))
    with pytest.raises(GenerationError, match="out of memory"):
        gen.generate("an apple")


def test_loader_failure_is_retried_next_call(tmp_path):
    calls = {"n": 0}

    def flaky_loader(settings):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("download interrupted")
        return FakeModel()

    gen = Generator(SETTINGS, flaky_loader, cache_dir=tmp_path, free_bytes=lambda p: 100 * GB)
    with pytest.raises(GenerationError, match="download interrupted"):
        gen.generate("x")
    assert gen.generate("x") == b"\x89PNG fake"


def test_concurrent_calls_load_once(tmp_path):
    gen, loader = make(tmp_path)
    threads = [threading.Thread(target=gen.generate, args=("x",)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert loader.loads == 1


def test_disk_check_blocks_download_when_low(tmp_path):
    spec = ModelSpec("m", "org/model", download_gb=6.0)
    with pytest.raises(GenerationError, match="free disk"):
        ensure_disk_space(spec, tmp_path, free_bytes=lambda p: 7 * GB)


def test_disk_check_passes_with_room_or_when_cached(tmp_path):
    spec = ModelSpec("m", "org/model", download_gb=6.0)
    ensure_disk_space(spec, tmp_path, free_bytes=lambda p: 20 * GB)
    (tmp_path / "models--org--model").mkdir()
    ensure_disk_space(spec, tmp_path, free_bytes=lambda p: 0)


def test_disk_check_handles_missing_cache_dir(tmp_path):
    spec = ModelSpec("m", "org/model", download_gb=6.0)
    seen: list[Path] = []
    ensure_disk_space(spec, tmp_path / "a" / "b", free_bytes=lambda p: seen.append(p) or 20 * GB)
    assert seen == [tmp_path]


def test_generate_runs_disk_check_before_loading(tmp_path):
    gen, loader = make(tmp_path, free_gb=1)
    with pytest.raises(GenerationError, match="free disk"):
        gen.generate("x")
    assert loader.loads == 0
