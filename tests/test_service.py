from pathlib import Path

import pytest

from anki_imagegen.anki_media import AnkiConnectError, AnkiMedia, AnkiUnreachableError
from anki_imagegen.config import GeneratorSettings
from anki_imagegen.generator import Generator
from anki_imagegen.service import ImageService, StoredImage

SETTINGS = GeneratorSettings(model="z-image-turbo", quantize=4, steps=9, width=512, height=512)


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    def generate_png(self, **kwargs) -> bytes:
        self.calls += 1
        return b"\x89PNG " + kwargs["prompt"].encode()


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def generator(model, tmp_path):
    return Generator(SETTINGS, lambda s: model, cache_dir=tmp_path, free_bytes=lambda p: 10**12)


def test_generate_for_note_stores_and_keeps_local_copy(fake_anki, generator, tmp_path):
    service = ImageService(generator, AnkiMedia(fake_anki.url), tmp_path / "output")
    result = service.generate_for_note("an apple", 42)
    assert result == StoredImage(
        filename="anki-img-42.png", local_path=str(tmp_path / "output" / "anki-img-42.png")
    )
    assert Path(result.local_path).read_bytes() == b"\x89PNG an apple"
    assert [r["action"] for r in fake_anki.requests] == ["version", "storeMediaFile"]


def test_regeneration_overwrites_same_file(fake_anki, generator, tmp_path):
    service = ImageService(generator, AnkiMedia(fake_anki.url), tmp_path / "output")
    service.generate_for_note("an apple", 42)
    result = service.generate_for_note("a green apple", 42)
    assert Path(result.local_path).read_bytes() == b"\x89PNG a green apple"
    assert list((tmp_path / "output").iterdir()) == [Path(result.local_path)]
    stored = [r["params"]["filename"] for r in fake_anki.requests if r["action"] == "storeMediaFile"]
    assert stored == ["anki-img-42.png", "anki-img-42.png"]


def test_unreachable_anki_fails_before_model_runs(generator, model, tmp_path):
    service = ImageService(generator, AnkiMedia("http://127.0.0.1:9", timeout=1), tmp_path / "output")
    with pytest.raises(AnkiUnreachableError, match="Open Anki"):
        service.generate_for_note("an apple", 42)
    assert model.calls == 0


@pytest.mark.parametrize(
    ("prompt", "note_id", "width", "height", "match"),
    [
        ("an apple", 0, None, None, "note_id"),
        ("   ", 42, None, None, "prompt"),
        ("an apple", 42, 500, None, "width"),
        ("an apple", 42, None, 2048, "height"),
    ],
)
def test_invalid_inputs_rejected_before_anki_and_model(
    fake_anki, generator, model, tmp_path, prompt, note_id, width, height, match
):
    service = ImageService(generator, AnkiMedia(fake_anki.url), tmp_path / "output")
    with pytest.raises(ValueError, match=match):
        service.generate_for_note(prompt, note_id, width, height)
    assert fake_anki.requests == []
    assert model.calls == 0


def test_store_failure_mentions_local_copy(fake_anki, generator, tmp_path):
    fake_anki.responses["storeMediaFile"] = {"result": None, "error": "collection is not available"}
    service = ImageService(generator, AnkiMedia(fake_anki.url), tmp_path / "output")
    with pytest.raises(AnkiConnectError, match="anki-img-42.png") as info:
        service.generate_for_note("an apple", 42)
    assert "collection is not available" in str(info.value)
    assert (tmp_path / "output" / "anki-img-42.png").exists()


def test_local_copy_failure_still_stores_in_anki(fake_anki, generator, tmp_path):
    blocked = tmp_path / "output"
    blocked.write_text("not a directory")  # makes the local write fail with OSError
    service = ImageService(generator, AnkiMedia(fake_anki.url), blocked)
    result = service.generate_for_note("an apple", 42)
    assert result == StoredImage(filename="anki-img-42.png", local_path="")
    stored = [r for r in fake_anki.requests if r["action"] == "storeMediaFile"]
    assert len(stored) == 1


def test_preview_writes_only_locally(fake_anki, generator, tmp_path):
    service = ImageService(generator, AnkiMedia(fake_anki.url), tmp_path / "output")
    first = Path(service.preview("an apple"))
    second = Path(service.preview("a pear", 256, 256))
    assert first != second
    assert first.parent == tmp_path / "output"
    assert first.name.startswith("preview-") and first.suffix == ".png"
    assert second.read_bytes() == b"\x89PNG a pear"
    assert fake_anki.requests == []
