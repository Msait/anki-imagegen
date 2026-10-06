import asyncio
import json
import shutil
import time
from pathlib import Path

import pytest
from mcp import Client

from anki_imagegen.anki_media import AnkiUnreachableError
from anki_imagegen.generator import GenerationError
from anki_imagegen.server import build_server
from anki_imagegen.service import StoredImage

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeService:
    def __init__(self, error: Exception | None = None, delay: float = 0.0) -> None:
        self.error = error
        self.delay = delay
        self.calls: list[tuple] = []

    def generate_for_note(self, prompt, note_id, width=None, height=None):
        self.calls.append(("generate", prompt, note_id, width, height))
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return StoredImage(filename=f"anki-img-{note_id}.png", local_path="/x/out.png")

    def preview(self, prompt, width=None, height=None):
        self.calls.append(("preview", prompt, width, height))
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return "/x/preview.png"


def call(server, tool: str, args: dict, progress_callback=None):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(tool, args, progress_callback=progress_callback)

    return asyncio.run(run())


def payload(result) -> dict:
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text((PROJECT_ROOT / "config.example.toml").read_text())
    (tmp_path / "prompt_guides").mkdir()
    shutil.copy(PROJECT_ROOT / "prompt_guides" / "example.md", tmp_path / "prompt_guides")
    return path


def test_lists_exactly_three_tools(config_path):
    async def run():
        async with Client(build_server(config_path, FakeService())) as client:
            return sorted(t.name for t in (await client.list_tools()).tools)

    assert asyncio.run(run()) == ["generate_image", "get_config", "preview_image"]


def test_get_config_returns_effective_deck_settings(config_path):
    server = build_server(config_path, FakeService())
    data = payload(call(server, "get_config", {"deck": "Vocabulary::Food"}))
    assert data["image_field"] == "Image"
    assert data["card_kind"] == "word"
    assert "{term}" in data["caption"]
    assert data["prompt_guide"].startswith("# Scene guide")
    assert "word" in data["prompt_rules"]
    assert "model" not in data  # [generator] is not exposed


def test_get_config_rereads_file(config_path):
    server = build_server(config_path, FakeService())
    config_path.write_text(config_path.read_text().replace("batch_size = 10", "batch_size = 3"))
    assert payload(call(server, "get_config", {"deck": "x"}))["batch_size"] == 3


def test_generate_image_passes_arguments(config_path):
    service = FakeService()
    data = payload(call(build_server(config_path, service), "generate_image",
                        {"prompt": "an apple", "note_id": 42, "width": 768}))
    assert data == {"filename": "anki-img-42.png", "local_path": "/x/out.png"}
    assert service.calls == [("generate", "an apple", 42, 768, None)]


def test_preview_image(config_path):
    data = payload(call(build_server(config_path, FakeService()), "preview_image", {"prompt": "x"}))
    assert data == {"local_path": "/x/preview.png"}


@pytest.mark.parametrize("tool, args", [("generate_image", {"prompt": "x", "note_id": 1}),
                                        ("preview_image", {"prompt": "x"})])
def test_long_generation_reports_progress(config_path, tool, args):
    # Clients abort a tool call that stays silent too long; a slow GPU must not look like a hang.
    updates = []

    async def on_progress(progress, total, message):
        updates.append((progress, message))

    server = build_server(config_path, FakeService(delay=0.35), heartbeat_seconds=0.1)
    payload(call(server, tool, args, progress_callback=on_progress))
    assert len(updates) >= 2
    assert [p for p, _ in updates] == sorted(p for p, _ in updates)
    assert "elapsed" in updates[0][1]


def test_failed_generation_after_heartbeats_keeps_message(config_path):
    server = build_server(config_path, FakeService(GenerationError("out of memory"), delay=0.25),
                          heartbeat_seconds=0.1)
    result = call(server, "generate_image", {"prompt": "x", "note_id": 1})
    assert result.is_error
    assert "out of memory" in result.content[0].text


@pytest.mark.parametrize(
    "error",
    [
        AnkiUnreachableError("Open Anki with AnkiConnect enabled"),
        GenerationError("image generation failed: out of memory"),
        ValueError("width must be an integer multiple of 16"),
        OSError("No space left on device"),
    ],
)
def test_expected_errors_reach_client_with_message(config_path, error):
    result = call(build_server(config_path, FakeService(error)), "generate_image",
                  {"prompt": "x", "note_id": 1})
    assert result.is_error
    assert str(error) in result.content[0].text


def test_broken_config_reaches_client_with_message(config_path):
    server = build_server(config_path, FakeService())
    config_path.write_text(config_path.read_text().replace('placement = "append"', 'placement = "top"'))
    result = call(server, "get_config", {"deck": "x"})
    assert result.is_error
    assert "placement" in result.content[0].text
