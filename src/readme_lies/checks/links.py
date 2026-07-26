"""Link, path, image and anchor checks.

All local and offline. External URLs are deliberately **not** fetched: that turns
a fast deterministic lint into a flaky network test, and good tools for it already
exist (`lychee`, `markdown-link-check`). This checks the claims only your own
repository can answer.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..model import Document, Finding, Level

#: Schemes that are somebody else's problem.
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)

#: Inline code that is worth treating as a path claim. Requires a directory
#: separator or a known source extension, so prose like `npm` or `--flag` is
#: never mistaken for a file.
_PATHY = re.compile(
    r"^[\w./@-]+(?:/[\w./@-]+)+/?$|"
    r"^[\w.-]+\.(?:py|ts|tsx|js|jsx|json|toml|ya?ml|md|txt|cfg|ini|lock|sh|rs|go|java|rb)$"
)

#: Never flag these — they are conventions, not files that must exist here.
_ALLOWED_MISSING = {
    ".env", ".env.local", "node_modules", "dist", "build", "venv", ".venv",
    "__pycache__", "coverage", "target", "out",
}


def _is_external(target: str) -> bool:
    return bool(_EXTERNAL.match(target)) or target.startswith("mailto:")


def _split_anchor(target: str) -> tuple[str, str | None]:
    if "#" not in target:
        return target, None
    path, _, anchor = target.partition("#")
    return path, anchor


class LinkChecker:
    """Checks that local links, images and anchors resolve."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def check(self, doc: Document) -> list[Finding]:
        findings: list[Finding] = []
        slugs = self._slugs(doc)
        base = doc.path.parent

        for link in doc.links:
            target = link.target.strip()
            if not target or _is_external(target):
                continue

            path_part, anchor = _split_anchor(unquote(target))

            if not path_part:
                # Pure in-document anchor, e.g. [Tests](#tests).
                if anchor and anchor.lower() not in slugs:
                    findings.append(self._bad_anchor(link.text, anchor, link.line, doc, slugs))
                continue

            resolved = (base / path_part).resolve()
            if resolved.exists():
                # A link into another local markdown file can still name a
                # heading that no longer exists there.
                if anchor and resolved.suffix.lower() == ".md":
                    finding = self._check_foreign_anchor(resolved, anchor, link, doc)
                    if finding:
                        findings.append(finding)
                continue

            kind = "image" if link.is_image else "link"
            findings.append(
                Finding(
                    code="missing-image" if link.is_image else "missing-link-target",
                    message=f"{kind} `{link.text or path_part}` points at `{path_part}`, which does not exist",
                    line=link.line,
                    level=Level.ERROR,
                    detail="The file was probably moved or renamed.",
                    source=doc.path,
                )
            )

        findings.extend(self._check_inline_paths(doc, base))
        return findings

    def _slugs(self, doc: Document) -> set[str]:
        """Heading slugs, with GitHub's `-1` suffixes for duplicates."""
        seen: dict[str, int] = {}
        slugs: set[str] = set()
        for heading in doc.headings:
            count = seen.get(heading.slug, 0)
            slugs.add(heading.slug if count == 0 else f"{heading.slug}-{count}")
            seen[heading.slug] = count + 1
        return slugs

    def _bad_anchor(
        self, text: str, anchor: str, line: int, doc: Document, slugs: set[str]
    ) -> Finding:
        suggestion = self._closest(anchor, slugs)
        return Finding(
            code="missing-anchor",
            message=f"`{text or anchor}` links to `#{anchor}`, but no heading has that anchor",
            line=line,
            level=Level.ERROR,
            detail=f"Did you mean `#{suggestion}`?" if suggestion else None,
            source=doc.path,
        )

    def _check_foreign_anchor(
        self, target: Path, anchor: str, link, doc: Document
    ) -> Finding | None:
        from ..parser import parse  # local import avoids a cycle

        try:
            other = parse(target)
        except OSError:
            return None
        if anchor.lower() in self._slugs(other):
            return None
        return Finding(
            code="missing-anchor",
            message=f"link to `{target.name}#{anchor}` names a heading that file does not have",
            line=link.line,
            level=Level.WARNING,
            source=doc.path,
        )

    def _check_inline_paths(self, doc: Document, base: Path) -> list[Finding]:
        from ..ignore import GitIgnore, basenames

        gitignore = GitIgnore.load(self.root)
        findings: list[Finding] = []

        for text, line in doc.inline_code:
            candidate = text.strip().rstrip("/")
            if not candidate or not _PATHY.match(candidate):
                continue
            if candidate in _ALLOWED_MISSING or Path(candidate).name in _ALLOWED_MISSING:
                continue
            if _is_external(candidate):
                continue
            if (base / candidate).exists() or (self.root / candidate).exists():
                continue
            # Generated output is *meant* to be absent from a clean checkout.
            if gitignore.ignores(candidate):
                continue
            # A bare filename may legitimately live in a subdirectory: a README
            # saying `App.test.tsx` means src/App.test.tsx, and is not a lie.
            if "/" not in candidate and Path(candidate).name in basenames(self.root):
                continue

            findings.append(
                Finding(
                    code="missing-path",
                    message=f"`{candidate}` is referenced but does not exist",
                    line=line,
                    level=Level.WARNING,
                    detail="If this is an example rather than a real path, ignore with "
                    "`--ignore missing-path` or rephrase it.",
                    source=doc.path,
                )
            )
        return findings

    @staticmethod
    def _closest(anchor: str, slugs: set[str]) -> str | None:
        import difflib

        matches = difflib.get_close_matches(anchor.lower(), sorted(slugs), n=1, cutoff=0.7)
        return matches[0] if matches else None
