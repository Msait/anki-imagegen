"""Local image model wrapper: prompt + size -> PNG bytes."""

from __future__ import annotations

import io
import logging
import random
import shutil
import threading
from pathlib import Path
from typing import Callable, Protocol

from anki_imagegen.config import GeneratorSettings, validate_size
from anki_imagegen.models import MODEL_SPECS, ModelSpec

log = logging.getLogger(__name__)

DISK_MARGIN_GB = 5.0


class GenerationError(RuntimeError):
    """The model could not be loaded or failed to produce an image."""


class ImageModel(Protocol):
    def generate_png(self, *, prompt: str, width: int, height: int, steps: int, seed: int) -> bytes: ...


ModelLoader = Callable[[GeneratorSettings], ImageModel]


def _disk_free(path: Path) -> int:
    return shutil.disk_usage(path).free


def _hf_cache_dir() -> Path:
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE)


def ensure_disk_space(spec: ModelSpec, cache_dir: Path, free_bytes: Callable[[Path], int]) -> None:
    """Refuse to start a download that would not fit; no-op if the repo is already cached."""
    if (cache_dir / f"models--{spec.hf_repo.replace('/', '--')}").is_dir():
        return
    probe = cache_dir
    while not probe.exists():
        probe = probe.parent
    needed_gb = spec.download_gb + DISK_MARGIN_GB
    free_gb = free_bytes(probe) / 1e9
    if free_gb < needed_gb:
        raise GenerationError(
            f"not enough free disk to download {spec.hf_repo}: "
            f"need ~{needed_gb:.0f} GB, have {free_gb:.1f} GB"
        )
    log.info("Downloading %s (~%.0f GB) on first use; this can take a while", spec.hf_repo, spec.download_gb)


class Generator:
    def __init__(
        self,
        settings: GeneratorSettings,
        loader: ModelLoader,
        cache_dir: Path | None = None,
        free_bytes: Callable[[Path], int] | None = None,
    ) -> None:
        self._settings = settings
        self._loader = loader
        self._cache_dir = cache_dir
        self._free_bytes = free_bytes or _disk_free
        self._model: ImageModel | None = None
        self._lock = threading.Lock()

    def resolve_request(self, prompt: str, width: int | None, height: int | None) -> tuple[str, int, int]:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt must not be empty")
        width = self._settings.width if width is None else width
        height = self._settings.height if height is None else height
        validate_size(width, height)
        return prompt, width, height

    def generate(
        self, prompt: str, width: int | None = None, height: int | None = None, seed: int | None = None
    ) -> bytes:
        prompt, width, height = self.resolve_request(prompt, width, height)
        seed = random.randrange(2**31) if seed is None else seed
        with self._lock:  # one generation at a time; the GPU is the bottleneck anyway
            model = self._ensure_loaded()
            try:
                return model.generate_png(
                    prompt=prompt, width=width, height=height, steps=self._settings.steps, seed=seed
                )
            except Exception as e:
                raise GenerationError(f"image generation failed: {type(e).__name__}: {e}") from e

    def _ensure_loaded(self) -> ImageModel:
        if self._model is None:
            spec = MODEL_SPECS[self._settings.model]
            ensure_disk_space(spec, self._cache_dir or _hf_cache_dir(), self._free_bytes)
            log.info("Loading model %s", spec.name)
            try:
                self._model = self._loader(self._settings)
            except Exception as e:
                raise GenerationError(f"failed to load {spec.name}: {type(e).__name__}: {e}") from e
            log.info("Model %s loaded", spec.name)
        return self._model


class _MfluxModel:
    def __init__(self, model) -> None:
        self._model = model

    def generate_png(self, *, prompt: str, width: int, height: int, steps: int, seed: int) -> bytes:
        result = self._model.generate_image(
            seed=seed, prompt=prompt, num_inference_steps=steps, width=width, height=height
        )
        buffer = io.BytesIO()
        result.image.save(buffer, format="PNG")
        return buffer.getvalue()


def load_mflux_model(settings: GeneratorSettings) -> ImageModel:
    """Import mflux lazily so tests and server startup stay fast."""
    from mflux.models.common.config import ModelConfig

    if settings.model == "z-image-turbo":
        from mflux.models.z_image import ZImage

        model = ZImage(
            model_config=ModelConfig.z_image_turbo(),
            model_path=MODEL_SPECS["z-image-turbo"].hf_repo,  # pre-quantized 4-bit
        )
    elif settings.model == "flux2-klein-4b":
        from mflux.models.flux2.variants import Flux2Klein

        model = Flux2Klein(model_config=ModelConfig.flux2_klein_4b(), quantize=settings.quantize)
    elif settings.model == "flux-schnell":
        from mflux.models.flux.variants.txt2img.flux import Flux1

        model = Flux1(model_config=ModelConfig.schnell(), quantize=settings.quantize)
    else:
        raise ValueError(f"unsupported model {settings.model!r}")
    return _MfluxModel(model)
