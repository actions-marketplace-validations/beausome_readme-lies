"""Verify documented commands **without running them**.

This is the check that makes the tool safe to point at any repository. Executing
a README's shell blocks is a remote-code-execution primitive; reading them is not.
Most command rot is statically detectable anyway:

* ``npm run dev`` — is ``dev`` actually in ``package.json`` scripts?
* ``python app.py`` — does ``app.py`` exist?
* ``make build`` — is ``build`` a target in the Makefile?
* ``cp .env.example .env`` — does the file being copied exist?
* ``pip install -r requirements.txt`` — does that requirements file exist?

Everything else is deliberately ignored. A linter that guesses at commands it
does not understand produces noise, and a noisy linter gets switched off.

``cd`` is tracked within a block, so ``cd frontend && npm run dev`` resolves the
script against ``frontend/package.json`` rather than the repo root.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from ..model import CodeBlock, Finding, Level

#: Package-manager subcommands that are built in rather than user-defined.
_BUILTIN_NPM_SCRIPTS = {
    "install", "i", "ci", "publish", "pack", "link", "audit", "outdated",
    "update", "init", "exec", "create", "login", "version", "run", "add",
    "remove", "dlx", "why", "list", "ls", "prune", "rebuild", "dedupe",
}

#: `npm test` and friends work with or without an explicit script entry.
_IMPLICIT_NPM_SCRIPTS = {"test", "start", "stop", "restart"}

_INTERPRETERS = {
    "python": (".py",),
    "python3": (".py",),
    "py": (".py",),
    "node": (".js", ".mjs", ".cjs", ".ts"),
    "deno": (".js", ".ts"),
    "bun": (".js", ".ts"),
    "ruby": (".rb",),
    "php": (".php",),
}

# Prompt prefixes to strip from documented lines.
#
# `#` is deliberately NOT a prompt here. It is technically the root prompt, but
# in a README it is overwhelmingly a comment - and treating `# python setup.py`
# as a command produced a false positive for a line the author had commented out.
# Missing a root-prompt command is the far cheaper mistake.
_PROMPT = re.compile(r"^\s*(?:\$|>|PS\s?>|\w+@[\w.-]+:[^$#]*\$)\s+")
_ENV_ASSIGN = re.compile(r"^[A-Z_][A-Z0-9_]*=\S*$")


def _iter_commands(block: CodeBlock) -> list[tuple[str, int]]:
    """Split a shell block into individual commands with their line numbers.

    Handles line continuations, comments, and the ``&&`` / ``||`` / ``;`` / ``|``
    separators. Output lines in ``console`` blocks (anything not prefixed with a
    prompt, once any prompt is seen) are dropped.
    """
    commands: list[tuple[str, int]] = []
    lines = block.content.splitlines()
    has_prompts = any(_PROMPT.match(line) for line in lines)

    pending = ""
    pending_line = 0

    for offset, raw in enumerate(lines, start=1):
        line_no = block.line + offset
        line = raw.rstrip()

        if has_prompts and not pending:
            # A console transcript: only prompted lines are commands.
            if not _PROMPT.match(line):
                continue
        line = _PROMPT.sub("", line)

        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not pending:
            pending_line = line_no
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue

        pending += stripped
        for part in re.split(r"&&|\|\||[;|]", pending):
            part = part.strip()
            if part:
                commands.append((part, pending_line))
        pending = ""

    if pending.strip():
        commands.append((pending.strip(), pending_line))

    return commands


def _read_scripts(package_json: Path) -> dict[str, str] | None:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    scripts = data.get("scripts")
    return scripts if isinstance(scripts, dict) else None


def _make_targets(makefile: Path) -> set[str]:
    targets: set[str] = set()
    try:
        for line in makefile.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([A-Za-z0-9_.\-/ ]+):(?!=)", line)
            if match:
                targets.update(part for part in match.group(1).split() if part)
    except OSError:
        return targets
    return targets


def _looks_like_path(token: str) -> bool:
    """Whether a token is plausibly a file this repo should contain."""
    if not token or token.startswith("-"):
        return False
    if "://" in token or token.startswith(("$", "<", "{", "*")):
        return False
    # Placeholders like <your-repo> or YOUR_KEY are documentation, not paths.
    if re.search(r"[<>{}]", token) or token.isupper():
        return False
    return "/" in token or "." in token


class CommandChecker:
    """Statically validates the commands a document documents."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def check(self, blocks: list[CodeBlock], source: Path) -> list[Finding]:
        findings: list[Finding] = []
        for block in blocks:
            if not block.is_shell:
                continue
            cwd = self.root
            for command, line in _iter_commands(block):
                cwd, more = self._check_command(command, line, cwd, source)
                findings.extend(more)
        return findings

    def _check_command(
        self, command: str, line: int, cwd: Path, source: Path
    ) -> tuple[Path, list[Finding]]:
        try:
            argv = shlex.split(command, comments=True)
        except ValueError:
            return cwd, []  # unbalanced quotes; not our problem to diagnose

        # Drop leading `VAR=value` assignments.
        while argv and _ENV_ASSIGN.match(argv[0]):
            argv = argv[1:]
        if not argv:
            return cwd, []

        program, args = argv[0], argv[1:]
        finding: Finding | None = None

        if program == "cd" and args:
            return self._resolve_cd(args[0], cwd), []

        if program in {"npm", "pnpm", "yarn", "bun"}:
            finding = self._check_package_script(program, args, line, cwd, source)
        elif program == "make":
            finding = self._check_make(args, line, cwd, source)
        elif program in _INTERPRETERS:
            finding = self._check_interpreter(program, args, line, cwd, source)
        elif program in {"cp", "mv"} and args:
            finding = self._check_exists(args[0], line, cwd, source, f"`{command}` copies")
        elif program in {"pip", "pip3"} and "-r" in args:
            index = args.index("-r")
            if index + 1 < len(args):
                finding = self._check_exists(
                    args[index + 1], line, cwd, source, "`pip install -r` reads"
                )
        elif program.startswith("./"):
            finding = self._check_exists(program, line, cwd, source, "the documented script")

        return cwd, [finding] if finding else []

    def _resolve_cd(self, target: str, cwd: Path) -> Path:
        if target in {"-", "~"} or target.startswith(("/", "$", "~")):
            return cwd  # absolute or magic; stop tracking rather than guess
        resolved = (cwd / target).resolve()
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError:
            return cwd  # escaped the repo; ignore
        return resolved if resolved.is_dir() else cwd

    def _check_exists(
        self, target: str, line: int, cwd: Path, source: Path, phrase: str
    ) -> Finding | None:
        if not _looks_like_path(target):
            return None
        path = cwd / target
        if path.exists():
            return None
        return Finding(
            code="missing-file",
            message=f"{phrase} `{target}`, which does not exist",
            line=line,
            level=Level.ERROR,
            detail="Rename it in the docs, or add the file.",
            source=source,
        )

    def _check_package_script(
        self, manager: str, args: list[str], line: int, cwd: Path, source: Path
    ) -> Finding | None:
        args = [a for a in args if not a.startswith("-")]
        if not args:
            return None

        script = args[1] if args[0] == "run" else args[0]
        if args[0] != "run":
            if script in _BUILTIN_NPM_SCRIPTS:
                return None
            # `yarn dev` and `bun dev` run scripts directly; `npm dev` does not.
            if manager == "npm" and script not in _IMPLICIT_NPM_SCRIPTS:
                return None

        package_json = cwd / "package.json"
        if not package_json.exists():
            return Finding(
                code="missing-package-json",
                message=f"`{manager} {' '.join(args)}` is documented, but there is no package.json here",
                line=line,
                level=Level.WARNING,
                detail=f"Looked in {self._rel(cwd)}. If the command runs elsewhere, document the `cd`.",
                source=source,
            )

        scripts = _read_scripts(package_json)
        if scripts is None:
            return None
        if script in scripts or script in _IMPLICIT_NPM_SCRIPTS:
            return None

        known = ", ".join(sorted(scripts)) or "none defined"
        return Finding(
            code="missing-script",
            message=f"`{manager} run {script}` is documented, but no such script exists",
            line=line,
            level=Level.ERROR,
            detail=f"package.json defines: {known}",
            source=source,
        )

    def _check_make(
        self, args: list[str], line: int, cwd: Path, source: Path
    ) -> Finding | None:
        targets = [a for a in args if not a.startswith("-")]
        if not targets:
            return None
        makefile = next(
            (cwd / name for name in ("Makefile", "makefile", "GNUmakefile") if (cwd / name).exists()),
            None,
        )
        if makefile is None:
            return Finding(
                code="missing-makefile",
                message=f"`make {targets[0]}` is documented, but there is no Makefile",
                line=line,
                level=Level.WARNING,
                detail=f"Looked in {self._rel(cwd)}.",
                source=source,
            )
        available = _make_targets(makefile)
        if not available or targets[0] in available:
            return None
        return Finding(
            code="missing-make-target",
            message=f"`make {targets[0]}` is documented, but the Makefile has no such target",
            line=line,
            level=Level.ERROR,
            detail=f"Targets found: {', '.join(sorted(available))}",
            source=source,
        )

    def _check_interpreter(
        self, program: str, args: list[str], line: int, cwd: Path, source: Path
    ) -> Finding | None:
        positional = [a for a in args if not a.startswith("-")]
        if not positional:
            return None
        if "-m" in args:
            return None  # module paths need import resolution; out of scope
        target = positional[0]
        if not target.endswith(_INTERPRETERS[program]):
            return None
        return self._check_exists(target, line, cwd, source, f"`{program}` is told to run")

    def _rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix() or "."
        except ValueError:
            return path.as_posix()
