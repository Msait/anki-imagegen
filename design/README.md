# Card design

The look of the three card types, kept apart from the image generator. Design
system (colours, type, components, rationale):
https://claude.ai/artifact/W2WpxSEtHG1HWfXqCy1tmG

```
design/
  tokens.css        colours (day + night), fonts, sizes, spacing: change the look here
  components.css    card parts (chip, term, image frame, banner, code); reads only tokens
  cards/<name>/     front.html, back.html (Anki template syntax), sample.toml for previews
  fonts/            woff2 files embedded in the cards + fonts.toml (the list) + licenses
  preview/          stand-in pictures for previews
```

| Design | For | Fields | Optional fields |
| --- | --- | --- | --- |
| `chunk` | a phrase recalled from a situation | Situation, Chunk | Example, Note, Image |
| `recognition` | a word or phrase to understand | Word, Meaning | IPA, Example, Image |
| `concept` | a technical term to explain | Term, Explanation | Topic, Question, Code, Image |

The chip at the top shows the card's deck (`{{Subdeck}}`). Your own note types
and decks belong in your `config.toml` (`[note_types]`), never in these files.

## Workflow

1. Edit `tokens.css`, `components.css` or a card's HTML.
2. `uv run anki-design preview` and open `output/design-preview/index.html`: every
   card, front and back, at phone width (AnkiDroid) and desktop width, day and night.
3. Map your note types once in `config.toml` (`[note_types]`, see `config.example.toml`).
4. With Anki desktop open: `uv run anki-design sync --dry-run`, then `uv run anki-design sync`.
5. Sync Anki with AnkiWeb, then sync AnkiDroid.

`sync` overwrites the note type's Styling and one card type's Front/Back, so make
changes here, not in Anki's template editor. The previous templates are saved in
`output/design-backups/<time>/` first. Fields stay as they are: a section such as
`{{#IPA}}…{{/IPA}}` is left out for a note type without an IPA field; a required
field that is missing stops the sync with a message.

## Phone first

Most reviews happen in AnkiDroid, so:

- Fonts are embedded (`_aic-*.woff2` in Anki media; the underscore keeps Check Media
  from deleting them), so cards look the same offline. Latin, IPA and Ukrainian
  Cyrillic are covered.
- `.mobile` (added by AnkiDroid and AnkiMobile) scales type and padding down in
  `tokens.css`; desktop keeps a 560px column.
- Night mode follows the app: `.night_mode` (AnkiDroid) and `.nightMode` (desktop).
- Every back starts the answer with `<hr id="answer">`; both apps scroll there, so on
  a phone the picture and the answer are on screen without scrolling.
- Code blocks scroll sideways inside themselves; the card never does.

## Fonts

To change a font, edit `fonts/fonts.toml`, run `uv run python scripts/fetch_fonts.py`,
update the `--font-*` stacks in `tokens.css`, and sync. Pick families whose Cyrillic
includes і ї є ґ; many Japanese fonts cover only Russian.
