"""License-claim check.

A README that says "MIT" with no LICENSE file leaves the terms legally
ambiguous — without an explicit license, default copyright applies and nobody
may reuse the code, whatever the README says. Worse is a README claiming one
license while the LICENSE file says another.

This exact bug shipped in a real repository during development of this tool,
which is why it is a check rather than a footnote.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import Document, Finding, Level

_LICENSE_FILENAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING")

#: Signatures that identify a license from its text, in specificity order.
_SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AGPL-3.0", ("gnu affero general public license",)),
    ("LGPL", ("gnu lesser general public license",)),
    ("GPL-3.0", ("gnu general public license", "version 3")),
    ("GPL-2.0", ("gnu general public license", "version 2")),
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MPL-2.0", ("mozilla public license", "2.0")),
    ("BSD-3-Clause", ("redistributions of source code", "neither the name")),
    ("BSD-2-Clause", ("redistributions of source code",)),
    ("Unlicense", ("this is free and unencumbered software",)),
    ("ISC", ("permission to use, copy, modify, and/or distribute",)),
    ("MIT", ("permission is hereby granted, free of charge",)),
)

#: How a README usually names a license.
_CLAIM = re.compile(
    r"\b(MIT|ISC|Apache(?:[ -]2(?:\.0)?)?|AGPL(?:[ -]?3(?:\.0)?)?|"
    r"LGPL|GPL(?:[ -]?[23](?:\.0)?)?|BSD(?:[ -]\d[ -]clause)?|MPL(?:[ -]?2(?:\.0)?)?|"
    r"Unlicense|CC0|proprietary)\b",
    re.IGNORECASE,
)


def _normalise(name: str) -> str:
    lowered = name.lower().replace(" ", "-").replace("_", "-")
    if lowered.startswith("apache"):
        return "Apache-2.0"
    if lowered.startswith("agpl"):
        return "AGPL-3.0"
    if lowered.startswith("lgpl"):
        return "LGPL"
    if lowered.startswith("gpl"):
        return "GPL-3.0" if "3" in lowered else "GPL-2.0" if "2" in lowered else "GPL"
    if lowered.startswith("mpl"):
        return "MPL-2.0"
    if lowered.startswith("bsd"):
        return "BSD-3-Clause" if "3" in lowered else "BSD-2-Clause" if "2" in lowered else "BSD"
    return name.upper() if lowered in {"mit", "isc", "cc0"} else name


def identify(text: str) -> str | None:
    """Best-effort identification of a license from its full text."""
    lowered = " ".join(text.lower().split())
    for name, markers in _SIGNATURES:
        if all(marker in lowered for marker in markers):
            return name
    return None


class LicenseChecker:
    """Compares the README's license claim against the LICENSE file."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def check(self, doc: Document) -> list[Finding]:
        claim, line = self._claim(doc)
        license_file = next(
            (self.root / name for name in _LICENSE_FILENAMES if (self.root / name).exists()),
            None,
        )

        if claim is None:
            return []

        if license_file is None:
            return [
                Finding(
                    code="missing-license-file",
                    message=f"the docs say this is {claim}-licensed, but there is no LICENSE file",
                    line=line,
                    level=Level.ERROR,
                    detail="Without one the terms are ambiguous and default copyright applies, "
                    "so nobody may legally reuse the code.",
                    source=doc.path,
                )
            ]

        try:
            actual = identify(license_file.read_text(encoding="utf-8"))
        except OSError:
            return []

        if actual is None or actual == claim:
            return []
        return [
            Finding(
                code="license-mismatch",
                message=f"the docs say {claim}, but {license_file.name} is {actual}",
                line=line,
                level=Level.ERROR,
                detail="Pick one. Conflicting license statements are worse than none.",
                source=doc.path,
            )
        ]

    def _claim(self, doc: Document) -> tuple[str | None, int]:
        """Find a license claim, preferring one under a License heading."""
        lines = doc.text.splitlines()

        heading_lines = [h.line for h in doc.headings if "licen" in h.text.lower()]
        for start in heading_lines:
            for offset in range(start, min(start + 6, len(lines))):
                match = _CLAIM.search(lines[offset])
                if match:
                    return _normalise(match.group(1)), offset + 1

        # Fall back to a badge or a sentence anywhere in the document.
        for index, line in enumerate(lines, start=1):
            if "licen" not in line.lower():
                continue
            match = _CLAIM.search(line)
            if match:
                return _normalise(match.group(1)), index
        return None, 1
