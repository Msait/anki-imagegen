"""Card design: build note type templates and styling from design/, preview them, push them to Anki.

    uv run anki-design preview          # output/design-preview/index.html, phone and desktop, day and night
    uv run anki-design sync --dry-run   # what would change in Anki
    uv run anki-design sync             # write templates, styling and fonts through AnkiConnect

AnkiDroid gets the changes through AnkiWeb sync: templates and styling travel with the
collection, fonts with the media.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from anki_imagegen.anki_media import AnkiConnectError, AnkiMedia
from anki_imagegen.config import ConfigError, NoteTypeLink, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DESIGN_DIR = PROJECT_ROOT / "design"
OUTPUT_DIR = PROJECT_ROOT / "output"
CSS_PARTS = ("fonts/fonts.css", "tokens.css", "components.css")
# Replacements Anki fills in itself; they are not note fields.
SPECIAL_FIELDS = {"FrontSide", "Tags", "Type", "Deck", "Subdeck", "Card", "CardFlag", "CardID"}
TAG = re.compile(r"{{(.*?)}}", re.S)
# What Anki renders for {{tts ...}}: a replay button (it speaks on its own when the side opens).
REPLAY_BUTTON = (
    '<a class="replay-button soundLink" href="#"><svg class="playImage" viewBox="0 0 64 64">'
    '<circle cx="32" cy="32" r="29"/><path d="M56.502,32.301l-37.502,20.101l0.329,-40.804l37.173,20.703Z"/></svg></a>'
)


class DesignError(ValueError):
    """A design file or a note type does not fit together."""


# --- templates ---------------------------------------------------------------------------


@dataclass
class Section:
    inverted: bool  # {{^Field}} instead of {{#Field}}
    field: str
    children: list


@dataclass
class Replacement:
    tag: str  # everything between the braces, filters included

    @property
    def field(self) -> str:
        return self.tag.rsplit(":", 1)[-1].strip()


def parse_template(text: str) -> list:
    """Anki template text -> tree of str, Replacement and Section nodes."""
    root: list = []
    stack: list[tuple[Section | None, list]] = [(None, root)]
    pos = 0
    for match in TAG.finditer(text):
        stack[-1][1].append(text[pos : match.start()])
        pos = match.end()
        tag = match[1].strip()
        if tag[:1] in "#^":
            section = Section(tag[0] == "^", tag[1:].strip(), [])
            stack[-1][1].append(section)
            stack.append((section, section.children))
        elif tag[:1] == "/":
            open_section = stack[-1][0]
            if open_section is None or open_section.field != tag[1:].strip():
                raise DesignError(f"unexpected {{{{{tag}}}}}")
            stack.pop()
        else:
            stack[-1][1].append(Replacement(tag))
    stack[-1][1].append(text[pos:])
    if len(stack) > 1:
        raise DesignError(f"{{{{#{stack[-1][0].field}}}}} is never closed")
    return root


def _serialize(nodes: list) -> str:
    out = []
    for node in nodes:
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, Replacement):
            out.append(f"{{{{{node.tag}}}}}")
        else:
            mark = "^" if node.inverted else "#"
            out.append(f"{{{{{mark}{node.field}}}}}{_serialize(node.children)}{{{{/{node.field}}}}}")
    return "".join(out)


def fit_template(text: str, fields: list[str]) -> str:
    """Adapt a design template to a note type's fields.

    A {{#Field}} section for a field the note type lacks is dropped and a {{^Field}}
    section is unwrapped, so optional parts (IPA, Example, Code) need no field. A plain
    {{Field}} outside such sections must exist."""
    have = set(fields) | SPECIAL_FIELDS
    missing: list[str] = []

    def fit(nodes: list) -> list:
        out: list = []
        for node in nodes:
            if isinstance(node, Section) and node.field not in have:
                if node.inverted:
                    out.extend(fit(node.children))
            elif isinstance(node, Section):
                out.append(Section(node.inverted, node.field, fit(node.children)))
            elif isinstance(node, Replacement) and node.field not in have:
                missing.append(node.field)
            else:
                out.append(node)
        return out

    fitted = _serialize(fit(parse_template(text)))
    if missing:
        raise DesignError(f"missing field(s) {', '.join(sorted(set(missing)))}")
    return fitted


def render_template(text: str, note: dict[str, str], front_side: str = "") -> str:
    """Render like Anki does, closely enough for previews."""

    def is_empty(value: str) -> bool:
        return not re.sub(r"<br\s*/?>|&nbsp;|\s", "", value)

    def render(nodes: list) -> str:
        out = []
        for node in nodes:
            if isinstance(node, str):
                out.append(node)
            elif isinstance(node, Replacement):
                if node.field == "FrontSide":
                    out.append(front_side)
                elif node.tag.startswith("tts "):
                    out.append(REPLAY_BUTTON)
                else:
                    value = note.get(node.field, "")
                    out.append(re.sub(r"<[^>]+>", "", value) if node.tag.startswith("text:") else value)
            elif is_empty(note.get(node.field, "")) == node.inverted:
                out.append(render(node.children))
        return "".join(out)

    return render(parse_template(text))


# --- design files ------------------------------------------------------------------------


@dataclass(frozen=True)
class CardDesign:
    name: str
    front: str
    back: str
    sample: dict[str, str]


def load_designs(design_dir: Path = DESIGN_DIR) -> dict[str, CardDesign]:
    designs = {}
    for folder in sorted(p for p in (design_dir / "cards").iterdir() if p.is_dir()):
        sample_path = folder / "sample.toml"
        designs[folder.name] = CardDesign(
            name=folder.name,
            front=(folder / "front.html").read_text(),
            back=(folder / "back.html").read_text(),
            sample=tomllib.loads(sample_path.read_text()) if sample_path.exists() else {},
        )
    return designs


def build_css(design_dir: Path = DESIGN_DIR) -> str:
    parts = ["/* Generated by `anki-design sync` from the design/ folder of anki-imagegen.\n"
             "   Edits made here in Anki are overwritten on the next sync: change design/ instead. */"]
    parts += [(design_dir / part).read_text().strip() for part in CSS_PARTS]
    return "\n\n".join(parts) + "\n"


def font_files(design_dir: Path = DESIGN_DIR) -> list[Path]:
    return sorted((design_dir / "fonts").glob("_*.woff2"))


# --- sync --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Planned:
    note_type: str
    template: str
    front: str
    back: str
    old_front: str
    old_back: str
    old_css: str
    other_templates: list[str]

    def changes(self, css: str) -> list[str]:
        names = [("front", self.front, self.old_front), ("back", self.back, self.old_back), ("styling", css, self.old_css)]
        return [name for name, new, old in names if new != old]


def plan(anki: AnkiMedia, links: dict[str, NoteTypeLink], designs: dict[str, CardDesign]) -> list[Planned]:
    """Read every linked note type and fit its design; raise before anything is written."""
    if not links:
        raise DesignError(
            "config.toml has no [note_types]: map your Anki note types to designs "
            f"({', '.join(designs)}), see config.example.toml"
        )
    existing = anki.model_names()
    planned, errors = [], []
    for note_type, link in links.items():
        where = f'note type "{note_type}"'
        if note_type not in existing:
            errors.append(f"{where} is not in Anki (have: {', '.join(sorted(existing))})")
            continue
        if link.design not in designs:
            errors.append(f'{where}: no design "{link.design}" in design/cards (have: {", ".join(designs)})')
            continue
        design = designs[link.design]
        templates = anki.model_templates(note_type)
        if link.template is None and len(templates) > 1:
            errors.append(
                f"{where} has {len(templates)} card types ({', '.join(templates)}); "
                'pick one in config.toml: { design = "...", template = "..." }'
            )
            continue
        template = link.template or next(iter(templates))
        if template not in templates:
            errors.append(f'{where} has no card type "{template}" (have: {", ".join(templates)})')
            continue
        fields = anki.model_field_names(note_type)
        try:
            front, back = fit_template(design.front, fields), fit_template(design.back, fields)
        except DesignError as e:
            errors.append(f"{where} (fields: {', '.join(fields)}): {e}. Rename or add the field in Anki")
            continue
        planned.append(
            Planned(
                note_type=note_type,
                template=template,
                front=front,
                back=back,
                old_front=templates[template]["Front"],
                old_back=templates[template]["Back"],
                old_css=anki.model_styling(note_type),
                other_templates=[t for t in templates if t != template],
            )
        )
    if errors:
        raise DesignError("\n".join(errors))
    return planned


def backup(planned: list[Planned], backup_dir: Path) -> Path:
    folder = backup_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    for p in planned:
        data = {"note_type": p.note_type, "template": p.template, "Front": p.old_front, "Back": p.old_back, "css": p.old_css}
        safe = re.sub(r"[^\w.-]+", "_", p.note_type)
        (folder / f"{safe}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return folder


def sync(anki: AnkiMedia, links: dict[str, NoteTypeLink], design_dir: Path, backup_dir: Path, dry_run: bool, out=print) -> None:
    designs = load_designs(design_dir)
    css = build_css(design_dir)
    planned = plan(anki, links, designs)
    for p in planned:
        changes = p.changes(css)
        out(f'{p.note_type} [{p.template}]: {"changes " + ", ".join(changes) if changes else "up to date"}')
        if p.other_templates:
            out(f"  also gets the new styling but keeps its HTML: {', '.join(p.other_templates)}")
    fonts = font_files(design_dir)
    if dry_run:
        out(f"dry run: nothing written ({len(fonts)} font files would be uploaded)")
        return
    folder = backup(planned, backup_dir)
    for font in fonts:
        anki.store_media(font.name, font.read_bytes())
    for p in planned:
        if p.changes(css):
            anki.update_model_templates(p.note_type, {p.template: {"Front": p.front, "Back": p.back}})
            anki.update_model_styling(p.note_type, css)
    out(f"previous templates saved in {folder}")
    out("done: sync Anki with AnkiWeb, then sync AnkiDroid")


# --- preview -----------------------------------------------------------------------------

DEVICES = (
    ("Phone · day", 390, "card card1 android mobile"),
    ("Phone · night", 390, "card card1 android mobile night_mode"),
    ("Desktop · day", 720, "card card1 mac"),
    ("Desktop · night", 720, "card card1 mac nightMode night_mode"),
)

PREVIEW_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Card design preview</title>
<style>
  body {{ margin: 0; padding: 24px 16px; background: #e9e6f0; color: #1f1b2e; font: 14px/1.4 system-ui, sans-serif; }}
  h1 {{ margin: 0 0 4px; font-size: 22px; }}
  h2 {{ margin: 40px 0 12px; font-size: 18px; }}
  .note {{ color: #5d5873; margin: 0 0 8px; }}
  .row {{ display: flex; gap: 16px; overflow-x: auto; padding-bottom: 8px; align-items: flex-start; }}
  figure {{ margin: 0; flex: none; }}
  figcaption {{ font-size: 12px; color: #5d5873; margin-bottom: 6px; }}
  iframe {{ display: block; border: 0; border-radius: 14px; background: #fff; box-shadow: 0 1px 4px rgba(0,0,0,.15); }}
</style></head><body>
<h1>Card design preview</h1>
<p class="note">Built from design/ with the sample notes in design/cards/*/sample.toml. Rebuild: <code>uv run anki-design preview</code></p>
{sections}
<script>
  addEventListener("message", (e) => {{
    const frame = [...document.querySelectorAll("iframe")].find((f) => f.contentWindow === e.source);
    if (frame) frame.style.height = e.data + "px";
  }});
</script>
</body></html>
"""

FRAME = """<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head>
<body class="{classes}"><div id="qa">{html}</div>
<script>const send = () => parent.postMessage(document.documentElement.scrollHeight, "*");
addEventListener("load", send); document.fonts.ready.then(send);</script></body></html>"""


def write_preview(design_dir: Path, out_dir: Path) -> Path:
    designs = load_designs(design_dir)
    css = build_css(design_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for asset in [*font_files(design_dir), *sorted((design_dir / "preview").glob("*"))]:
        shutil.copy(asset, out_dir / asset.name)
    sections = []
    for design in designs.values():
        front = render_template(design.front, design.sample)
        back = render_template(design.back, design.sample, front_side=front)
        for side, body in (("front", front), ("back", back)):
            frames = "".join(
                f'<figure><figcaption>{label}</figcaption><iframe width="{width}" height="400" '
                f'srcdoc="{html.escape(FRAME.format(css=css, classes=classes, html=body))}"></iframe></figure>'
                for label, width, classes in DEVICES
            )
            sections.append(f"<h2>{design.name} · {side}</h2><div class=\"row\">{frames}</div>")
    page = out_dir / "index.html"
    page.write_text(PREVIEW_PAGE.format(sections="\n".join(sections)))
    return page


# --- command line ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anki-design", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preview", help="write output/design-preview/index.html")
    sync_parser = sub.add_parser("sync", help="push templates, styling and fonts to Anki")
    sync_parser.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    sync_parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.toml")
    args = parser.parse_args(argv)

    try:
        if args.command == "preview":
            print(write_preview(DESIGN_DIR, OUTPUT_DIR / "design-preview"))
        else:
            links = load_config(args.config).note_types
            sync(AnkiMedia(), links, DESIGN_DIR, OUTPUT_DIR / "design-backups", args.dry_run)
    except (DesignError, ConfigError, AnkiConnectError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
