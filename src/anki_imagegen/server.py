"""MCP server (stdio) exposing image generation for Anki cards."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
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


def build_server(config_path: Path, service: ImageService) -> MCPServer:
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
    def generate_image(
        prompt: str, note_id: int, width: int | None = None, height: int | None = None
    ) -> dict[str, str]:
        """Generate an image for an Anki note and store it in Anki's media as
        anki-img-<note_id>.png (overwrites on regeneration). Returns the media filename to
        put in <img src="..."> and the path of the local copy. Takes tens of seconds."""
        try:
            return asdict(service.generate_for_note(prompt, note_id, width, height))
        except EXPECTED_ERRORS as e:
            raise ToolError(str(e)) from e

    @mcp.tool()
    def preview_image(prompt: str, width: int | None = None, height: int | None = None) -> dict[str, str]:
        """Generate an image to a local file only (not stored in Anki), to try out a prompt."""
        try:
            return {"local_path": service.preview(prompt, width, height)}
        except EXPECTED_ERRORS as e:
            raise ToolError(str(e)) from e

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
