# anki-imagegen

Local illustrations for Anki flashcards on Apple Silicon. Claude Code reads
your cards (via an Anki MCP server), writes a prompt per card, and calls this
MCP server, which runs an MLX image model on the Mac GPU and stores the PNG in
Anki through AnkiConnect.

- stdio MCP only, no listening ports; talks to `127.0.0.1:8765` and downloads
  weights from huggingface.co once.
- All policy lives in `config.toml` (`[defaults]` + per-deck overrides). It is
  personal and not tracked: start from `config.example.toml`, and from
  `prompt_guides/example.md` for a deck's scene guide.

## Requirements

- Apple Silicon Mac, Python 3.13, [uv](https://docs.astral.sh/uv/)
- Anki desktop with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on, running
- An Anki MCP server in Claude Code for reading and updating notes

## Install

```sh
uv sync
cp config.example.toml config.toml   # then set field names and deck overrides
uv run pytest -m slow -s   # downloads the model weights once and makes output/smoke.png
claude mcp add --scope user anki-imagegen -- uv --directory "$PWD" run anki-imagegen
ln -s "$PWD/skills/anki-images" ~/.claude/skills/anki-images
```

Run the slow test before the first real use so the first tool call does not
spend minutes downloading weights.

## Use

In Claude Code: `/anki-images add pictures to deck "German B1"`.

Tools: `get_config(deck)`, `generate_image(prompt, note_id, width?, height?)`,
`preview_image(prompt, width?, height?)`. Images are stored as
`anki-img-<noteId>.png`; a copy of every image stays in `output/`.

## Card design

The cards' look lives in `design/` (tokens, components, one folder per card type)
and is pushed to Anki's note types with:

```sh
uv run anki-design preview         # output/design-preview/index.html
uv run anki-design sync --dry-run  # then without --dry-run; Anki must be open
```

AnkiDroid picks it up through AnkiWeb sync. Details: `design/README.md`.

## Develop

```sh
uv run pytest              # fast tests
uv run pytest -m slow -s   # real model
```
