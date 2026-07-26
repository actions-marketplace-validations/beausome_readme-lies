"""Command line interface.

Exit codes are the contract with CI: 0 clean, 1 findings at or above the
configured level, 2 for a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .core import DEFAULT_GLOBS, check
from .model import Finding, Level

_COLOURS = {"error": "\033[31m", "warning": "\033[33m", "dim": "\033[2m", "reset": "\033[0m"}


def _use_colour(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def _paint(text: str, colour: str, enabled: bool) -> str:
    return f"{_COLOURS[colour]}{text}{_COLOURS['reset']}" if enabled else text


def format_text(findings: Sequence[Finding], root: Path, documents: int, colour: bool) -> str:
    lines: list[str] = []
    for finding in findings:
        tag = _paint(finding.level.value, finding.level.value, colour)
        location = _paint(finding.location(root), "dim", colour)
        lines.append(f"{location} {tag} {finding.message}  [{finding.code}]")
        if finding.detail:
            lines.append(_paint(f"    {finding.detail}", "dim", colour))

    errors = sum(1 for f in findings if f.level is Level.ERROR)
    warnings = len(findings) - errors
    plural = "" if documents == 1 else "s"

    if not findings:
        lines.append(f"No lies found in {documents} document{plural}. Your docs tell the truth.")
    else:
        lines.append("")
        lines.append(
            f"{errors} error{'' if errors == 1 else 's'}, "
            f"{warnings} warning{'' if warnings == 1 else 's'} "
            f"in {documents} document{plural}."
        )
    return "\n".join(lines)


def format_json(findings: Sequence[Finding], root: Path, documents: int) -> str:
    return json.dumps(
        {
            "version": __version__,
            "documents_checked": documents,
            "summary": {
                "errors": sum(1 for f in findings if f.level is Level.ERROR),
                "warnings": sum(1 for f in findings if f.level is Level.WARNING),
            },
            "findings": [
                {
                    "code": f.code,
                    "level": f.level.value,
                    "message": f.message,
                    "detail": f.detail,
                    "file": f.location(root).rsplit(":", 1)[0],
                    "line": f.line,
                }
                for f in findings
            ],
        },
        indent=2,
    )


def format_github(findings: Sequence[Finding], root: Path) -> str:
    """GitHub Actions workflow commands, so findings annotate the diff."""
    out: list[str] = []
    for finding in findings:
        file = finding.location(root).rsplit(":", 1)[0]
        message = finding.message + (f" — {finding.detail}" if finding.detail else "")
        out.append(
            f"::{finding.level.value} file={file},line={finding.line},"
            f"title=readme-lies ({finding.code})::{message}"
        )
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="readme-lies",
        description="Find claims in your docs that are no longer true.",
    )
    parser.add_argument(
        "path", nargs="?", default=".", type=Path, help="Repository root (default: .)"
    )
    parser.add_argument(
        "--glob",
        action="append",
        dest="globs",
        metavar="PATTERN",
        help=f"Document glob, repeatable (default: {', '.join(DEFAULT_GLOBS)})",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="CODE",
        help="Suppress a finding code, repeatable (e.g. missing-path)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "github"),
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on warnings as well as errors",
    )
    parser.add_argument("--version", action="version", version=f"readme-lies {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    root = args.path.resolve()
    if not root.is_dir():
        print(f"readme-lies: {args.path} is not a directory", file=sys.stderr)
        return 2

    findings, documents = check(root, args.globs or DEFAULT_GLOBS, args.ignore)

    if not documents:
        print(f"readme-lies: no markdown found under {args.path}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(format_json(findings, root, len(documents)))
    elif args.format == "github":
        output = format_github(findings, root)
        if output:
            print(output)
        print(format_text(findings, root, len(documents), colour=False), file=sys.stderr)
    else:
        print(format_text(findings, root, len(documents), _use_colour(sys.stdout)))

    if any(f.level is Level.ERROR for f in findings):
        return 1
    if args.strict and findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
