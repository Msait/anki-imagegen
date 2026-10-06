"""MCP server (stdio) exposing image generation for Anki cards."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, TypeVar

import anyio
import anyio.to_thread
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from anki_imagegen.anki_media import AnkiConnectError, AnkiMedia
from anki_imagegen.config import load_config
from anki_imagegen.generator import GenerationError, Generator, load_mflux_model
from anki_imagegen.service import ImageService

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Errors whose message is useful to Claude. mcp hides the text of any other exception.
# ConfigError is a ValueError; OSError covers a full disk or unwritable output/.
EXPECTED_ERRORS = (ValueError, OSError, AnkiConnectError, GenerationError)

log = logging.getLogger("anki_imagegen")

# Clients abort a tool call that sends nothing for too long; under memory pressure one
# image can take most of an hour, so keep reporting progress while the GPU works.
HEARTBEAT_SECONDS = 15.0

T = TypeVar("T")


async def _run_with_heartbeat(ctx: Context, interval: float, fn: Callable[[], T]) -> T:
    """Run blocking fn on a worker thread, reporting elapsed time every interval seconds."""
    start = time.monotonic()

    async def beat() -> None:
        while True:
            await anyio.sleep(interval)
            elapsed = time.monotonic() - start
            await ctx.report_progress(elapsed, message=f"generating, {elapsed:.0f}s elapsed")

    outcome: list[T] = []
    async with anyio.create_task_group() as tg:
        tg.start_soon(beat)
        try:
            outcome.append(await anyio.to_thread.run_sync(fn))
        except EXPECTED_ERRORS as e:
            error = e  # raised outside the task group so it is not wrapped in an ExceptionGroup
        else:
            error = None
        tg.cancel_scope.cancel()
    if error is not None:
        raise ToolError(str(error)) from error
    return outcome[0]


def build_server(config_path: Path, service: ImageService, heartbeat_seconds: float = HEARTBEAT_SECONDS) -> MCPServer:
    mcp = MCPServer("anki-imagegen")

    @mcp.tool()
    def get_config(deck: str) -> dict[str, Any]:
        """Effective image settings for an Anki deck: config.toml [defaults] overlaid with
        the deck's (and its parent decks') overrides. Call this first for every run."""
        try:
            return load_config(config_path).for_deck(deck).to_dict()
        except EXPECTED_ERRORS as e:
            raise ToolError(str(e)) from e

    @mcp.tool()
    async def generate_image(
        prompt: str, note_id: int, ctx: Context, width: int | None = None, height: int | None = None
    ) -> dict[str, str]:
        """Generate an image for an Anki note and store it in Anki's media as
        anki-img-<note_id>.png (overwrites on regeneration). Returns the media filename to
        put in <img src="..."> and the path of the local copy. Takes a few minutes."""
        stored = await _run_with_heartbeat(
            ctx, heartbeat_seconds, lambda: service.generate_for_note(prompt, note_id, width, height)
        )
        return asdict(stored)

    @mcp.tool()
    async def preview_image(
        prompt: str, ctx: Context, width: int | None = None, height: int | None = None
    ) -> dict[str, str]:
        """Generate an image to a local file only (not stored in Anki), to try out a prompt."""
        path = await _run_with_heartbeat(ctx, heartbeat_seconds, lambda: service.preview(prompt, width, height))
        return {"local_path": path}

    return mcp


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    config_path = Path(os.environ.get("ANKI_IMAGEGEN_CONFIG", PROJECT_ROOT / "config.toml"))
    config = load_config(config_path)  # fail loudly at startup on a broken config
    generator = Generator(config.generator, load_mflux_model)
    service = ImageService(generator, AnkiMedia(), PROJECT_ROOT / "output")
    log.info("anki-imagegen ready (model %s, config %s)", config.generator.model, config_path)
    build_server(config_path, service).run()
