from pathlib import Path

import pytest

from anki_imagegen.config import ConfigError, load_config, validate_size

VALID = """
[generator]
model = "z-image-turbo"
quantize = 4
steps = 9
width = 512
height = 512

[defaults]
style = "flat vector illustration, no text"
term_field = "Front"
meaning_field = "Back"
image_field = "Back"
placement = "append"
skip_if_has_image = true
batch_size = 10
card_kind = "auto"
caption = ""
constraints = "NOT 3D render. No other text in the image."
prompt_guide = ""

[prompt_rules]
word = "a single clear object depicting '{term}'"
concept = "a visual metaphor for '{term}': {meaning}"

[decks."German B1"]
card_kind = "word"
image_field = "Picture"

[decks."CS Concepts"]
card_kind = "concept"
style = "isometric illustration, no text"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_unknown_deck_gets_defaults(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    deck = cfg.for_deck("Spanish")
    assert deck.image_field == "Back"
    assert deck.card_kind == "auto"
    assert deck.batch_size == 10
    assert deck.prompt_rules["word"] == "a single clear object depicting '{term}'"


def test_deck_overrides_defaults(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    deck = cfg.for_deck("German B1")
    assert deck.card_kind == "word"
    assert deck.image_field == "Picture"
    assert deck.style == "flat vector illustration, no text"


def test_subdeck_inherits_parent_overrides(tmp_path):
    text = VALID + '\n[decks."German B1::Verbs"]\nplacement = "prepend"\n'
    cfg = load_config(write(tmp_path, text))
    deck = cfg.for_deck("German B1::Verbs")
    assert deck.image_field == "Picture"   # from parent
    assert deck.placement == "prepend"     # from subdeck
    assert cfg.for_deck("German B1::Nouns").image_field == "Picture"


def test_to_dict_has_all_documented_keys(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert set(cfg.for_deck("x").to_dict()) == {
        "style", "term_field", "meaning_field", "image_field", "placement",
        "skip_if_has_image", "batch_size", "card_kind", "caption", "constraints", "prompt_guide", "prompt_rules",
    }


def test_generator_settings(tmp_path):
    gen = load_config(write(tmp_path, VALID)).generator
    assert (gen.model, gen.quantize, gen.steps, gen.width, gen.height) == (
        "z-image-turbo", 4, 9, 512, 512)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('placement = "append"', 'placement = "top"', "placement"),
        ('card_kind = "auto"', 'card_kind = "image"', "card_kind"),
        ("batch_size = 10", "batch_size = 0", "batch_size"),
        ("batch_size = 10", 'batch_size = "10"', "batch_size"),
        ("skip_if_has_image = true", "skip_if_has_image = 1", "skip_if_has_image"),
        ('model = "z-image-turbo"', 'model = "sdxl-turbo"', "model"),
        ("width = 512", "width = 500", "width"),
        ("height = 512", "height = 2048", "height"),
        ("steps = 9", "steps = 0", "steps"),
        ("quantize = 4", "quantize = 5", "quantize"),
        ('caption = ""', "caption = true", "caption"),
        ('caption = ""', 'caption = "Bold text at the bottom"', "caption"),
        ('prompt_guide = ""', 'prompt_guide = "guides/missing.md"', "missing.md"),
        ("concept = \"a visual metaphor for '{term}': {meaning}\"",
         "concept = \"a visual metaphor\"", "concept"),
        ("word = \"a single clear object depicting '{term}'\"",
         "word = \"an object depicting {word}\"", "word"),
    ],
)
def test_invalid_values_fail_loudly(tmp_path, old, new, message):
    assert old in VALID
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, VALID.replace(old, new)))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("batch_size = 10", "batch_size = 10\nbatchsize = 5", "batchsize"),
        ('image_field = "Picture"', 'image_field = "Picture"\nimgfield = "X"', "imgfield"),
        ("steps = 9", "steps = 9\nseed = 1", "seed"),
        ("[prompt_rules]", "[promt_rules]", "promt_rules"),
    ],
)
def test_unknown_keys_fail_loudly(tmp_path, old, new, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, VALID.replace(old, new)))


def test_missing_default_key_fails(tmp_path):
    with pytest.raises(ConfigError, match="term_field"):
        load_config(write(tmp_path, VALID.replace('term_field = "Front"\n', "")))


def test_missing_file_and_bad_toml(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")
    with pytest.raises(ConfigError, match="TOML"):
        load_config(write(tmp_path, "[defaults\n"))


@pytest.mark.parametrize(("w", "h"), [(256, 256), (512, 768), (1024, 1024)])
def test_validate_size_accepts(w, h):
    validate_size(w, h)


@pytest.mark.parametrize(("w", "h"), [(500, 512), (512, 128), (2048, 512), (True, 512)])
def test_validate_size_rejects(w, h):
    with pytest.raises(ValueError):
        validate_size(w, h)


def test_deck_can_set_caption_template(tmp_path):
    text = VALID + 'caption = \'Bold text on a banner: "{term}"\'\n'  # appended to [decks."CS Concepts"]
    cfg = load_config(write(tmp_path, text))
    assert cfg.for_deck("CS Concepts").caption == 'Bold text on a banner: "{term}"'
    assert cfg.for_deck("German B1").caption == ""


def test_prompt_guide_text_is_returned_for_deck(tmp_path):
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "cs.md").write_text("# Scene guide\nDraw metaphors.\n")
    cfg = load_config(write(tmp_path, VALID + 'prompt_guide = "guides/cs.md"\n'))
    assert cfg.for_deck("CS Concepts").prompt_guide == "# Scene guide\nDraw metaphors.\n"
    assert cfg.for_deck("CS Concepts::Graphs").prompt_guide == "# Scene guide\nDraw metaphors.\n"
    assert cfg.for_deck("German B1").prompt_guide == ""


def test_rule_may_use_only_meaning(tmp_path):
    text = VALID.replace("concept = \"a visual metaphor for '{term}': {meaning}\"",
                         "concept = \"a visual metaphor scene: {meaning}\"")
    assert load_config(write(tmp_path, text)).for_deck("x").prompt_rules["concept"] == (
        "a visual metaphor scene: {meaning}")
