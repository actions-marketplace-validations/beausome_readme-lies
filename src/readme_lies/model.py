"""Shared types.

Findings carry a line number because a docs linter that says "something is wrong"
without saying *where* is barely better than no linter at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Level(str, Enum):
    """How confident we are that this is really broken."""

    #: Definitely wrong: the thing the docs point at does not exist.
    ERROR = "error"
    #: Probably wrong, but the check has to guess (a path that might be an
    #: example, a command we only partly understand).
    WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """One claim in the docs that does not hold up.

    Attributes:
        code: Stable machine-readable id, e.g. ``missing-script``. Used for
            ``--ignore`` and for grouping in the JSON report.
        message: One line, written to be read in a CI log.
        line: 1-indexed line in the source document.
        level: :class:`Level`.
        detail: Optional second line with the fix, or with why we're unsure.
        source: The document the finding came from.
    """

    code: str
    message: str
    line: int
    level: Level = Level.ERROR
    detail: Optional[str] = None
    source: Optional[Path] = None

    def location(self, root: Optional[Path] = None) -> str:
        """``README.md:42`` style location, relative to ``root`` when given."""
        if self.source is None:
            return f"line {self.line}"
        path = self.source
        if root is not None:
            try:
                path = self.source.relative_to(root)
            except ValueError:
                pass
        return f"{path.as_posix()}:{self.line}"


@dataclass(frozen=True)
class CodeBlock:
    """A fenced code block."""

    lang: str
    content: str
    #: Line of the opening fence; the first content line is ``line + 1``.
    line: int

    @property
    def is_shell(self) -> bool:
        return self.lang.lower() in {
            "sh", "bash", "shell", "zsh", "console", "terminal", "shell-session",
        }


@dataclass(frozen=True)
class Link:
    """A markdown link or image."""

    text: str
    target: str
    line: int
    is_image: bool = False


@dataclass(frozen=True)
class Heading:
    """A markdown heading, with its GitHub anchor slug."""

    text: str
    level: int
    line: int
    slug: str


@dataclass
class Document:
    """A parsed markdown document."""

    path: Path
    text: str
    blocks: list[CodeBlock] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    inline_code: list[tuple[str, int]] = field(default_factory=list)
