---
name: anki-images
description: Use when the user wants illustrations for Anki flashcards — adding images to existing cards in a deck, regenerating an image for a card, or creating new cards (from a word list or topic) with images. Uses the local anki-imagegen MCP server and the Anki MCP server.
---

# Anki images

All policy (which field, style, prompt templates, batch size) comes from
`get_config`. Never edit `config.toml`; if the user wants different policy,
tell them which key to change.

## Procedure

1. **Settings.** Call `mcp__anki-imagegen__get_config(deck)` with the exact deck
   name (subdecks like `A::B` inherit `A`'s overrides).
2. **Select cards.**
   - Existing cards: search the deck with the Anki MCP
     (`deck:"<name>"`), then read each note's fields. The search also returns
     cards from subdecks: call `get_config` once per distinct deck the notes
     actually live in, and use that deck's settings for its notes. When
     `skip_if_has_image` is true, skip notes whose `image_field` already
     contains `<img`. Tell the user how many will be processed and skipped,
     and ask before starting if there are more than `batch_size`.
   - New cards: create the notes first with the Anki MCP (you need the
     `noteId`), then treat them as existing cards.
   - Regeneration ("regenerate for note X", optionally with a prompt): process
     just that note, ignoring `skip_if_has_image`.
3. **Build a prompt per card.**
   - Kind: `card_kind` if it is `word` or `concept`; for `auto`, use `word` for a
     single concrete word or short phrase that can be drawn as an object or
     action, otherwise `concept`.
   - If `prompt_guide` is not empty, it is the deck's scene-writing guide:
     read it before the first card and follow it for every scene. It wins over
     the generic advice below; if it says a card cannot be drawn, skip the card
     and report it as "not drawable".
   - Read the card (`term_field`, and `meaning_field` with HTML removed) and
     write English visual descriptions for the placeholders:
     - `{term}`: the concrete scene that shows the word, e.g. `der Apfel` →
       "a young girl biting into a crisp red apple in a sunny orchard".
     - `{meaning}`: a scene that works as a memorable metaphor, with characters,
       emotion, setting, lighting and motion, e.g. "won't budge" → "a stubborn
       grumpy donkey planting its hooves in the dirt while a sweating farmer
       pulls hard on a rope, sunny countryside with a wooden fence".
     - Never put the foreign word, the answer, or any quoted word into these
       descriptions: the model draws quoted words as text on the image.
   - Prompt = `style` + `. ` + scene (`prompt_rules[kind]` with placeholders
     filled) + `. ` + `constraints`, then, if `caption` is not empty,
     `. ` + `caption` with `{term}` replaced by the `term_field` value (HTML
     removed, upper case). The caption is the only place text may appear.
4. **Generate in batches of `batch_size`.** For each card call
   `mcp__anki-imagegen__generate_image(prompt, note_id)`, one card at a time,
   never several calls in parallel (the GPU serves one image at a time). It returns
   `filename`. Then update `image_field` with the Anki MCP:
   - tag = `<img src="<filename>">`
   - if the field already contains `src="<filename>"` (regeneration): leave the
     field unchanged; the media file was overwritten.
   - `append`: current field + `<br>` + tag (just the tag if the field is empty)
   - `prepend`: tag + `<br>` + current field
   - `replace`: tag only

   Read the field right before updating: update replaces the whole field value.
   If a call fails, record the error for that card and continue with the next.
   If the error says Anki is not reachable, stop and ask the user to open Anki.
   If the anki-imagegen server is disconnected, or three calls in a row fail
   with the same error, stop and report instead of continuing the batch.
5. **Report after each batch:** processed / skipped / failed counts, a list of
   `term → prompt` for processed cards, and the errors. Ask before the next batch.

To try a prompt without touching Anki, use `preview_image(prompt)` and give the
user the returned local path.

Note: Anki may show the old picture after regeneration until the card is
reopened, because it caches media by filename.
