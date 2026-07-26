"""Knowing which files are *supposed* to be missing.

The first version of the path check flagged `results/leaderboard.csv` and
`dist/index.html` — generated artefacts that a clean checkout correctly does not
have. Those are false positives, and false positives are how a linter earns its
place in a `# TODO: re-enable` comment.

Two defences:

* Anything matched by `.gitignore` is expected to be absent.
* A bare filename is searched for by basename before being reported, so
  `App.test.tsx` resolves to `src/App.test.tsx` rather than being called a lie.
"""

from __future__ import annotations

import fnmatch
from functools import lru_cache
from pathlib import Path

from .core import SKIP_DIRS


class GitIgnore:
    """A deliberately small `.gitignore` matcher.

    Supports the subset that matters for this purpose: comments, blank lines,
    directory suffixes, leading-slash anchoring and glob patterns. Negation
    (`!pattern`) is honoured in order. Anything more exotic falls through as
    "not ignored", which is the safe direction — worst case we report a finding
    the user can silence.
    """

    def __init__(self, patterns: list[str]) -> None:
        self.rules: list[tuple[str, bool]] = []
        for raw in patterns:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            self.rules.append((line.rstrip("/"), negated))

    @classmethod
    def load(cls, root: Path) -> "GitIgnore":
        path = root / ".gitignore"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        return cls(lines)

    def ignores(self, relative: str) -> bool:
        """Whether a repo-relative path would be ignored by git."""
        relative = relative.strip("/")
        if not relative:
            return False

        segments = relative.split("/")
        ignored = False

        for pattern, negated in self.rules:
            anchored = pattern.startswith("/")
            clean = pattern.lstrip("/")

            if anchored:
                matched = fnmatch.fnmatch(relative, clean) or relative.startswith(clean + "/")
            else:
                # An unanchored pattern matches at any depth, as git does.
                matched = (
                    fnmatch.fnmatch(relative, clean)
                    or any(fnmatch.fnmatch(seg, clean) for seg in segments)
                    or fnmatch.fnmatch(relative, f"*/{clean}")
                    or relative.startswith(clean + "/")
                )

            if matched:
                ignored = not negated

        return ignored


@lru_cache(maxsize=8)
def basenames(root: Path) -> frozenset[str]:
    """Every filename in the repository, for resolving bare references.

    Cached per root: a README can mention dozens of files and walking the tree
    once is plenty.
    """
    names: set[str] = set()
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        names.add(path.name)
    return frozenset(names)
