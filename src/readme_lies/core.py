"""Orchestration: find documents, run checks, collect findings."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from .checks.commands import CommandChecker
from .checks.license import LicenseChecker
from .checks.links import LinkChecker
from .model import Finding, Level
from .parser import parse

#: Documents checked when no explicit paths are given.
DEFAULT_GLOBS = ("README.md", "README.markdown", "readme.md", "docs/**/*.md", "*.md")

#: Directories never worth walking into.
SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__",
    ".tox", ".mypy_cache", ".pytest_cache", "vendor", "target", "site-packages",
}

#: Line-level opt-out, e.g. `<!-- readme-lies: ignore-next-line -->`.
IGNORE_NEXT = "readme-lies: ignore-next-line"
IGNORE_FILE = "readme-lies: ignore-file"


def find_documents(root: Path, patterns: Sequence[str] = DEFAULT_GLOBS) -> list[Path]:
    """Locate markdown documents under ``root``, deduplicated and sorted."""
    found: dict[Path, None] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            found.setdefault(path.resolve(), None)
    return list(found)


def _suppressed_lines(text: str) -> set[int]:
    """Lines silenced by an `ignore-next-line` comment above them."""
    suppressed: set[int] = set()
    for index, line in enumerate(text.splitlines(), start=1):
        if IGNORE_NEXT in line:
            suppressed.add(index + 1)
    return suppressed


def check_document(path: Path, root: Path) -> list[Finding]:
    """Run every check against a single document."""
    doc = parse(path)
    if IGNORE_FILE in doc.text:
        return []

    findings: list[Finding] = []
    findings.extend(LinkChecker(root).check(doc))
    findings.extend(LicenseChecker(root).check(doc))
    findings.extend(CommandChecker(root).check(doc.blocks, doc.path))

    suppressed = _suppressed_lines(doc.text)
    findings = [f for f in findings if f.line not in suppressed]
    return sorted(findings, key=lambda f: (f.line, f.code))


def check(
    root: Path,
    patterns: Sequence[str] = DEFAULT_GLOBS,
    ignore: Iterable[str] = (),
) -> tuple[list[Finding], list[Path]]:
    """Check a repository.

    Args:
        root: Repository root.
        patterns: Globs, relative to ``root``, selecting documents.
        ignore: Finding codes to drop.

    Returns:
        ``(findings, documents_checked)``.
    """
    ignored = set(ignore)
    documents = find_documents(root, patterns)

    findings: list[Finding] = []
    for path in documents:
        findings.extend(f for f in check_document(path, root) if f.code not in ignored)
    return findings, documents


def worst_level(findings: Sequence[Finding]) -> Level | None:
    if any(f.level is Level.ERROR for f in findings):
        return Level.ERROR
    if findings:
        return Level.WARNING
    return None
