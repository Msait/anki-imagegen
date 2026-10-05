# Scene guide: example vocabulary deck

A template for a deck's scene-writing rules. Copy it, rename it, and point the
deck's `prompt_guide` at the copy. Claude reads the guide before the first card
and follows it for every scene.

Describe the deck first: what is on the front and the back, and where the image
appears. Example: the front is a foreign word, the back is its translation, and
the image goes into the `Image` field together with the word banner.

## Prompt frame

The prompt is `style. SCENE. constraints. caption`. Style, constraints and the
caption banner come from config and never change, so every card looks the same.
Only the scene changes from card to card.

## Scene formula

**Who + what they do (and this shows the meaning) + a visual cue + where.**

Name the exact emotion in the scene ("delighted, eyes sparkling"), not only the
body's reaction.

## Techniques by word type

| Word type | Technique | Example |
|---|---|---|
| Object (apple, umbrella) | One character using the object in a typical place | A girl opens a yellow umbrella in the rain |
| Action (to run, to cook) | The action at its most recognisable moment | A boy mid-stride on a running track |
| Emotion or state (tired, proud) | Body language plus anime symbols: sweat drop, sparkles, gloom lines, blush | Slumped shoulders, gloom lines above the head |
| Abstraction (freedom, deadline) | Visual metaphor: turn the abstraction into an object | A bird leaving an open cage; a giant ticking clock |

## Avoid

- More than 1–2 characters and one main object: the image must read on a phone.
- Any text except the banner; never put words in quotes inside the scene.

If no technique fits (articles, particles, connectors), skip the card and report
it as "not drawable".
