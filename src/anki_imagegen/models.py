"""Registry of supported image models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    hf_repo: str
    download_gb: float  # measured in the spike; used for the free-disk check


MODEL_SPECS: dict[str, ModelSpec] = {
    spec.name: spec
    for spec in (
        ModelSpec("z-image-turbo", "filipstrand/Z-Image-Turbo-mflux-4bit", 6.0),
        ModelSpec("flux2-klein-4b", "black-forest-labs/FLUX.2-klein-4B", 16.0),
        ModelSpec("flux-schnell", "black-forest-labs/FLUX.1-schnell", 34.0),
    )
}
