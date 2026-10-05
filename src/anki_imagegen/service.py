"""Orchestrates one image: validate, check Anki, generate, keep a local copy, store."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from anki_imagegen.anki_media import AnkiConnectError, AnkiMedia, media_filename
from anki_imagegen.generator import Generator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredImage:
    filename: str
    local_path: str


class ImageService:
    def __init__(self, generator: Generator, anki: AnkiMedia, output_dir: Path) -> None:
        self._generator = generator
        self._anki = anki
        self._output_dir = output_dir

    def generate_for_note(
        self, prompt: str, note_id: int, width: int | None = None, height: int | None = None
    ) -> StoredImage:
        filename = media_filename(note_id)
        prompt, width, height = self._generator.resolve_request(prompt, width, height)
        self._anki.version()  # fail fast before spending GPU time
        png = self._generator.generate(prompt, width, height)
        try:
            local_path = str(self._write_local(filename, png))
        except OSError as e:  # the local copy is for review only; don't lose the image over it
            log.warning("could not save local copy of %s: %s", filename, e)
            local_path = ""
        try:
            stored = self._anki.store_media(filename, png)
        except AnkiConnectError as e:
            kept = f"generated image kept at {local_path}" if local_path else "no local copy"
            raise type(e)(f"{e} ({kept})") from e
        return StoredImage(filename=stored, local_path=local_path)

    def preview(self, prompt: str, width: int | None = None, height: int | None = None) -> str:
        png = self._generator.generate(prompt, width, height)
        name = f"preview-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.png"
        return str(self._write_local(name, png))

    def _write_local(self, name: str, png: bytes) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / name
        path.write_bytes(png)
        return path
