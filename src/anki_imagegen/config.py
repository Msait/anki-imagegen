"""Load config.toml and compute effective per-deck settings."""

from __future__ import annotations

import string
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from anki_imagegen.models import MODEL_SPECS

PLACEMENTS = ("append", "prepend", "replace")
CARD_KINDS = ("auto", "word", "concept")
QUANTIZE_LEVELS = (4, 8)
MIN_SIDE, MAX_SIDE, SIDE_STEP = 256, 1024, 16
PROMPT_PLACEHOLDERS = {"term", "meaning"}

DECK_KEY_TYPES: dict[str, type] = {
    "style": str,
    "term_field": str,
    "meaning_field": str,
    "image_field": str,
    "placement": str,
    "skip_if_has_image": bool,
    "batch_size": int,
    "card_kind": str,
    "caption": str,  # banner template with {term}; "" = no text on the image
    "constraints": str,  # appended after the scene
    "prompt_guide": str,  # markdown file (relative to config.toml) with scene-writing rules
}
GENERATOR_KEY_TYPES: dict[str, type] = {
    "model": str,
    "quantize": int,
    "steps": int,
    "width": int,
    "height": int,
}
TOP_LEVEL_KEYS = {"generator", "defaults", "prompt_rules", "decks", "note_types"}


class ConfigError(ValueError):
    """config.toml is missing, malformed or has invalid values."""


def validate_size(width: int, height: int) -> None:
    for name, value in (("width", width), ("height", height)):
        if type(value) is not int or not MIN_SIDE <= value <= MAX_SIDE or value % SIDE_STEP:
            raise ValueError(
                f"{name} must be an integer multiple of {SIDE_STEP} "
                f"between {MIN_SIDE} and {MAX_SIDE}, got {value!r}"
            )


@dataclass(frozen=True)
class GeneratorSettings:
    model: str
    quantize: int
    steps: int
    width: int
    height: int


@dataclass(frozen=True)
class NoteTypeLink:
    """Which card design (design/cards/<design>) a note type gets, and on which card type."""

    design: str
    template: str | None = None  # card type name; None = the note type's only card type


@dataclass(frozen=True)
class DeckSettings:
    style: str
    term_field: str
    meaning_field: str
    image_field: str
    placement: str
    skip_if_has_image: bool
    batch_size: int
    card_kind: str
    caption: str
    constraints: str
    prompt_guide: str  # the guide's text, not its path
    prompt_rules: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Config:
    generator: GeneratorSettings
    defaults: dict[str, Any]
    prompt_rules: dict[str, str]
    decks: dict[str, dict[str, Any]]
    guides: dict[str, str]  # prompt_guide path -> file text
    note_types: dict[str, NoteTypeLink] = field(default_factory=dict)  # note type name -> design

    def for_deck(self, deck: str) -> DeckSettings:
        """Defaults overlaid with every ancestor deck's overrides, root first."""
        merged = dict(self.defaults)
        parts = deck.split("::")
        for depth in range(1, len(parts) + 1):
            merged.update(self.decks.get("::".join(parts[:depth]), {}))
        merged["prompt_guide"] = self.guides.get(merged["prompt_guide"], "")
        return DeckSettings(**merged, prompt_rules=dict(self.prompt_rules))


def load_config(path: Path) -> Config:
    try:
        raw = tomllib.loads(Path(path).read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e

    _check_keys("top level", raw, TOP_LEVEL_KEYS)
    generator = _table(raw, "generator")
    _check_keys("[generator]", generator, set(GENERATOR_KEY_TYPES), required=True)
    _check_types("[generator]", generator, GENERATOR_KEY_TYPES)
    _check_generator(generator)

    defaults = _table(raw, "defaults")
    _check_keys("[defaults]", defaults, set(DECK_KEY_TYPES), required=True)
    _check_deck_values("[defaults]", defaults)

    prompt_rules = _table(raw, "prompt_rules")
    _check_keys("[prompt_rules]", prompt_rules, {"word", "concept"}, required=True)
    _check_prompt_rules(prompt_rules)

    decks = raw.get("decks", {})
    if not isinstance(decks, dict):
        raise ConfigError("[decks] must be a table of deck tables")
    for name, overrides in decks.items():
        where = f'[decks."{name}"]'
        if not isinstance(overrides, dict):
            raise ConfigError(f"{where} must be a table")
        _check_keys(where, overrides, set(DECK_KEY_TYPES))
        _check_deck_values(where, overrides)

    guides = _load_guides(Path(path).parent, [defaults, *decks.values()])
    note_types = _note_types(raw.get("note_types", {}))

    return Config(
        generator=GeneratorSettings(**generator),
        defaults=defaults,
        prompt_rules=prompt_rules,
        decks=decks,
        guides=guides,
        note_types=note_types,
    )


def _note_types(raw: Any) -> dict[str, NoteTypeLink]:
    if not isinstance(raw, dict):
        raise ConfigError("[note_types] must be a table of note type names")
    links: dict[str, NoteTypeLink] = {}
    for name, value in raw.items():
        where = f'[note_types] "{name}"'
        if isinstance(value, str):
            value = {"design": value}
        if not isinstance(value, dict):
            raise ConfigError(f'{where} must be a design name or {{ design = "...", template = "..." }}')
        _check_keys(where, value, {"design", "template"})
        if not isinstance(value.get("design"), str) or not value["design"]:
            raise ConfigError(f"{where}: design must be a non-empty string")
        if "template" in value and (not isinstance(value["template"], str) or not value["template"]):
            raise ConfigError(f"{where}: template must be a non-empty string")
        links[name] = NoteTypeLink(design=value["design"], template=value.get("template"))
    return links


def _load_guides(base_dir: Path, tables: list[dict[str, Any]]) -> dict[str, str]:
    guides: dict[str, str] = {}
    for table in tables:
        rel = table.get("prompt_guide", "")
        if rel and rel not in guides:
            try:
                guides[rel] = (base_dir / rel).read_text()
            except OSError as e:
                raise ConfigError(f"prompt_guide {rel!r} cannot be read: {e}") from e
    return guides


def _table(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"missing [{name}] table")
    return value


def _check_keys(where: str, table: dict[str, Any], allowed: set[str], required: bool = False) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}")
    missing = sorted(allowed - set(table)) if required else []
    if missing:
        raise ConfigError(f"{where}: missing key(s) {', '.join(missing)}")


def _check_types(where: str, table: dict[str, Any], types: dict[str, type]) -> None:
    for key, value in table.items():
        # `type(...) is` so that true/false is not accepted as an int
        if type(value) is not types[key]:
            raise ConfigError(f"{where}: {key} must be {types[key].__name__}, got {value!r}")


def _check_generator(generator: dict[str, Any]) -> None:
    if generator["model"] not in MODEL_SPECS:
        raise ConfigError(f"[generator]: model must be one of {', '.join(MODEL_SPECS)}")
    if generator["quantize"] not in QUANTIZE_LEVELS:
        raise ConfigError(f"[generator]: quantize must be one of {QUANTIZE_LEVELS}")
    if not 1 <= generator["steps"] <= 50:
        raise ConfigError("[generator]: steps must be between 1 and 50")
    try:
        validate_size(generator["width"], generator["height"])
    except ValueError as e:
        raise ConfigError(f"[generator]: {e}") from e


def _check_deck_values(where: str, table: dict[str, Any]) -> None:
    _check_types(where, table, DECK_KEY_TYPES)
    if "placement" in table and table["placement"] not in PLACEMENTS:
        raise ConfigError(f"{where}: placement must be one of {', '.join(PLACEMENTS)}")
    if "card_kind" in table and table["card_kind"] not in CARD_KINDS:
        raise ConfigError(f"{where}: card_kind must be one of {', '.join(CARD_KINDS)}")
    if table.get("caption") and "{term}" not in table["caption"]:
        raise ConfigError(f"{where}: caption must contain {{term}} (or be empty)")
    if "batch_size" in table and not 1 <= table["batch_size"] <= 100:
        raise ConfigError(f"{where}: batch_size must be between 1 and 100")


def _check_prompt_rules(rules: dict[str, Any]) -> None:
    for kind, rule in rules.items():
        if not isinstance(rule, str):
            raise ConfigError(f"[prompt_rules]: {kind} must be a string")
        names = {field for _, field, _, _ in string.Formatter().parse(rule) if field is not None}
        if not names & PROMPT_PLACEHOLDERS:
            raise ConfigError(f"[prompt_rules]: {kind} must contain {{term}} or {{meaning}}")
        unknown = sorted(names - PROMPT_PLACEHOLDERS)
        if unknown:
            raise ConfigError(f"[prompt_rules]: {kind} uses unknown placeholder(s) {unknown}")
