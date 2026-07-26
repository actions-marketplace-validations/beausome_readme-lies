"""Markdown parsing, with no dependencies.

A full CommonMark parser is not needed here and would be the only runtime
dependency in the project. What the checks need is narrow: fenced code blocks,
links, images, headings and inline code, each with a line number.

The one thing worth being careful about is **not reading inside fenced blocks**.
A README that documents `[a](b)` syntax, or shows a shell command containing a
path, must not have those treated as real claims — otherwise the linter reports
failures for text that was only ever an example.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import CodeBlock, Document, Heading, Link

_FENCE = re.compile(r"^(?P<indent>\s{0,3})(?P<fence>```+|~~~+)\s*(?P<lang>[^\s`]*)")
_ATX_HEADING = re.compile(r"^\s{0,3}(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
_LINK = re.compile(r"(?P<img>!)?\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def slugify(text: str) -> str:
    """Convert heading text to a GitHub anchor slug.

    GitHub lowercases, drops anything that is not a word character, space or
    hyphen, then turns spaces into hyphens. Emoji and punctuation vanish, which
    is why ``## 🦴 Nerd Neck`` anchors as ``#-nerd-neck``.
    """
    # Strip markdown emphasis and inline code markers first; they are not part
    # of the rendered text the slug is built from.
    text = re.sub(r"[`*_]", "", text)
    # Links inside headings contribute only their text.
    text = _LINK.sub(lambda m: m.group("text"), text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    # Each whitespace character becomes its own hyphen - GitHub does not collapse
    # runs, so "C++ / Rust" anchors as `c--rust`, not `c-rust`.
    return re.sub(r"\s", "-", text).strip("-")


def _strip_comments(text: str) -> str:
    """Blank out HTML comments, preserving line count so numbers stay right."""

    def blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return _HTML_COMMENT.sub(blank, text)


def parse(path: Path, text: str | None = None) -> Document:
    """Parse a markdown file into the pieces the checks care about.

    Args:
        path: Location of the document, used for reporting.
        text: Contents, read from ``path`` when omitted.

    Returns:
        A :class:`Document`.
    """
    raw = text if text is not None else path.read_text(encoding="utf-8")
    doc = Document(path=path, text=raw)

    cleaned = _strip_comments(raw)
    lines = cleaned.splitlines()

    fence: str | None = None
    fence_lang = ""
    fence_start = 0
    buffer: list[str] = []

    for index, line in enumerate(lines, start=1):
        match = _FENCE.match(line)

        if fence is not None:
            # Inside a block: only a matching closing fence matters.
            if match and match.group("fence")[0] == fence[0] and len(match.group("fence")) >= len(fence):
                doc.blocks.append(
                    CodeBlock(lang=fence_lang, content="\n".join(buffer), line=fence_start)
                )
                fence, fence_lang, buffer = None, "", []
            else:
                buffer.append(line)
            continue

        if match:
            fence = match.group("fence")
            fence_lang = match.group("lang")
            fence_start = index
            buffer = []
            continue

        heading = _ATX_HEADING.match(line)
        if heading:
            text_part = heading.group("text")
            doc.headings.append(
                Heading(
                    text=text_part,
                    level=len(heading.group("hashes")),
                    line=index,
                    slug=slugify(text_part),
                )
            )

        for link in _LINK.finditer(line):
            doc.links.append(
                Link(
                    text=link.group("text"),
                    target=link.group("target"),
                    line=index,
                    is_image=bool(link.group("img")),
                )
            )

        # Inline code that is inside a link was already captured as the link
        # target; capturing it again would double-report.
        masked = _LINK.sub(lambda m: " " * len(m.group(0)), line)
        for code in _INLINE_CODE.finditer(masked):
            doc.inline_code.append((code.group(1), index))

    # An unclosed fence at EOF still holds content worth checking.
    if fence is not None:
        doc.blocks.append(CodeBlock(lang=fence_lang, content="\n".join(buffer), line=fence_start))

    return doc
