import json

import pytest

from anki_imagegen.anki_media import AnkiMedia
from anki_imagegen.config import NoteTypeLink
from anki_imagegen.design import (
    DESIGN_DIR,
    DesignError,
    build_css,
    fit_template,
    font_files,
    load_designs,
    render_template,
    sync,
    write_preview,
)

BACK = '<h1>{{Word}}</h1>{{#IPA}}<i>{{IPA}}</i>{{/IPA}}{{^Image}}<b>{{Word}}</b>{{/Image}}<hr id="answer">{{Meaning}}'


def test_fit_drops_sections_for_missing_optional_fields():
    fitted = fit_template(BACK, ["Word", "Meaning", "Image"])
    assert "IPA" not in fitted
    assert "{{^Image}}<b>{{Word}}</b>{{/Image}}" in fitted


def test_fit_unwraps_inverted_section_for_missing_field():
    assert "{{^Image}}" not in fit_template(BACK, ["Word", "Meaning"])
    assert "<b>{{Word}}</b>" in fit_template(BACK, ["Word", "Meaning"])


def test_fit_keeps_template_when_all_fields_exist():
    assert fit_template(BACK, ["Word", "Meaning", "Image", "IPA"]) == BACK


def test_fit_reports_missing_required_field():
    with pytest.raises(DesignError, match="missing field.*Meaning"):
        fit_template(BACK, ["Word"])


def test_fit_ignores_special_fields_and_filters():
    assert fit_template("{{FrontSide}}{{text:Word}}", ["Word"]) == "{{FrontSide}}{{text:Word}}"


@pytest.mark.parametrize("bad", ["{{#A}}x", "{{/A}}", "{{#A}}{{/B}}"])
def test_unbalanced_sections_are_rejected(bad):
    with pytest.raises(DesignError):
        fit_template(bad, ["A", "B"])


def test_render_like_anki():
    note = {"Word": "salt", "Meaning": "сіль", "IPA": "", "Image": "<br>"}
    assert render_template(BACK, note) == '<h1>salt</h1><b>salt</b><hr id="answer">сіль'
    assert render_template("{{FrontSide}}|{{text:Meaning}}", {"Meaning": "<b>x</b>"}, "F") == "F|x"


def test_tts_renders_a_replay_button_and_needs_its_field():
    assert "replay-button" in render_template("{{tts en_US:Chunk}}", {"Chunk": "hi"})
    with pytest.raises(DesignError, match="Chunk"):
        fit_template("{{tts en_US:Chunk}}", ["Word"])


def test_chunk_design_fits_the_current_chunk_note_type():
    chunk = load_designs()["chunk"]
    back = fit_template(chunk.back, ["Situation", "Chunk", "Example", "Note", "Image"])
    assert back.index('id="answer"') < back.index("{{Chunk}}") < back.index("{{Image}}") < back.index("{{Example}}")
    assert "{{tts en_US:Chunk}}" in back


def test_recognition_design_reads_the_word_aloud_on_the_back():
    recognition = load_designs()["recognition"]
    back = fit_template(recognition.back, ["Word", "Meaning", "Image"])
    assert back.index("{{Word}}") < back.index("{{tts en_US:Word}}") < back.index('id="answer"')
    assert "tts" not in recognition.front  # like the current note type: spoken with the answer only


def test_shipped_designs_fit_their_samples():
    designs = load_designs()
    assert set(designs) == {"chunk", "recognition", "concept"}
    for design in designs.values():
        fields = list(design.sample)
        assert "{{" not in render_template(fit_template(design.front, fields), design.sample)
        assert "{{" not in render_template(fit_template(design.back, fields), design.sample)
        assert 'id="answer"' in design.back


def test_css_includes_every_font_file():
    css = build_css()
    files = font_files()
    assert files
    for font in files:
        assert font.name in css
    assert ".night_mode" in css and ".nightMode" in css


def test_preview_is_written(tmp_path):
    page = write_preview(DESIGN_DIR, tmp_path)
    text = page.read_text()
    assert "recognition · back" in text and "Phone · night" in text
    assert (tmp_path / font_files()[0].name).exists()


@pytest.fixture
def anki_with_model(fake_anki):
    fake_anki.responses.update(
        {
            "modelNames": {"result": ["Basic", "English Chunks"], "error": None},
            "modelFieldNames": {"result": ["Chunk", "Situation", "Image"], "error": None},
            "modelTemplates": {"result": {"Card 1": {"Front": "{{Situation}}", "Back": "{{Chunk}}"}}, "error": None},
            "modelStyling": {"result": {"css": ".card {}"}, "error": None},
            "updateModelTemplates": {"result": None, "error": None},
            "updateModelStyling": {"result": None, "error": None},
        }
    )
    return fake_anki


def actions(fake):
    return [r["action"] for r in fake.requests]


def test_sync_dry_run_writes_nothing(anki_with_model, tmp_path):
    lines = []
    sync(AnkiMedia(anki_with_model.url), {"English Chunks": NoteTypeLink("chunk")}, DESIGN_DIR, tmp_path, True, lines.append)
    assert "changes front, back, styling" in lines[0]
    assert not {"storeMediaFile", "updateModelTemplates", "updateModelStyling"} & set(actions(anki_with_model))
    assert not any(tmp_path.iterdir())


def test_sync_backs_up_then_writes(anki_with_model, tmp_path):
    sync(AnkiMedia(anki_with_model.url), {"English Chunks": NoteTypeLink("chunk")}, DESIGN_DIR, tmp_path, False, lambda _: None)
    [saved] = list(tmp_path.glob("*/English_Chunks.json"))
    assert json.loads(saved.read_text())["Front"] == "{{Situation}}"
    sent = {r["action"]: r["params"] for r in anki_with_model.requests}
    assert "aic--chunks" in sent["updateModelTemplates"]["model"]["templates"]["Card 1"]["Front"]
    assert "@font-face" in sent["updateModelStyling"]["model"]["css"]
    assert actions(anki_with_model).count("storeMediaFile") == len(font_files())


def test_sync_rejects_unknown_note_type_before_writing(anki_with_model, tmp_path):
    with pytest.raises(DesignError, match='"English Words" is not in Anki'):
        sync(AnkiMedia(anki_with_model.url), {"English Words": NoteTypeLink("recognition")}, DESIGN_DIR, tmp_path, False)
    assert "updateModelTemplates" not in actions(anki_with_model)


def test_sync_reports_missing_field(anki_with_model, tmp_path):
    with pytest.raises(DesignError, match="missing field.*Term"):
        sync(AnkiMedia(anki_with_model.url), {"English Chunks": NoteTypeLink("concept")}, DESIGN_DIR, tmp_path, False)


def test_sync_needs_template_choice_for_several_card_types(anki_with_model, tmp_path):
    two = {"Card 1": {"Front": "", "Back": ""}, "Card 2": {"Front": "", "Back": ""}}
    anki_with_model.responses["modelTemplates"] = {"result": two, "error": None}
    with pytest.raises(DesignError, match="2 card types"):
        sync(AnkiMedia(anki_with_model.url), {"English Chunks": NoteTypeLink("chunk")}, DESIGN_DIR, tmp_path, True)
    sync(AnkiMedia(anki_with_model.url), {"English Chunks": NoteTypeLink("chunk", "Card 2")}, DESIGN_DIR, tmp_path, True, lambda _: None)


def test_sync_without_mapping_explains(anki_with_model, tmp_path):
    with pytest.raises(DesignError, match="no \\[note_types\\]"):
        sync(AnkiMedia(anki_with_model.url), {}, DESIGN_DIR, tmp_path, True)
