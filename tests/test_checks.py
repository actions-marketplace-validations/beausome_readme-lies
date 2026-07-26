"""Behaviour of every check.

Each test builds a tiny throwaway repository, so nothing depends on the state of
this one and the suite runs offline in milliseconds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from readme_lies.core import check, check_document
from readme_lies.model import Level
from readme_lies.parser import parse, slugify


def build(tmp_path: Path, readme: str, files: dict[str, str] | None = None) -> Path:
    """Create a repo with a README and any supporting files."""
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    for name, content in (files or {}).items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def codes(findings) -> list[str]:
    return [f.code for f in findings]


# --------------------------------------------------------------------------- #
# Commands: verified without being executed
# --------------------------------------------------------------------------- #

class TestCommands:
    def test_flags_npm_script_that_does_not_exist(self, tmp_path):
        root = build(
            tmp_path,
            "# App\n\n```bash\nnpm run dev\n```\n",
            {"package.json": json.dumps({"scripts": {"build": "vite build"}})},
        )
        findings = check_document(root / "README.md", root)
        assert codes(findings) == ["missing-script"]
        assert "dev" in findings[0].message
        # The fix belongs in the message, not in the user's head.
        assert "build" in findings[0].detail

    def test_accepts_a_script_that_exists(self, tmp_path):
        root = build(
            tmp_path,
            "```bash\nnpm run build\n```\n",
            {"package.json": json.dumps({"scripts": {"build": "vite build"}})},
        )
        assert check_document(root / "README.md", root) == []

    def test_npm_builtins_are_not_scripts(self, tmp_path):
        root = build(
            tmp_path,
            "```bash\nnpm install\nnpm ci\nnpm test\n```\n",
            {"package.json": json.dumps({"scripts": {}})},
        )
        assert check_document(root / "README.md", root) == []

    def test_yarn_runs_scripts_without_the_run_keyword(self, tmp_path):
        root = build(
            tmp_path,
            "```bash\nyarn dev\n```\n",
            {"package.json": json.dumps({"scripts": {"start": "x"}})},
        )
        assert codes(check_document(root / "README.md", root)) == ["missing-script"]

    def test_cd_changes_where_the_script_is_looked_up(self, tmp_path):
        """`cd frontend && npm run dev` must resolve against frontend/."""
        root = build(
            tmp_path,
            "```bash\ncd frontend && npm run dev\n```\n",
            {
                "package.json": json.dumps({"scripts": {}}),
                "frontend/package.json": json.dumps({"scripts": {"dev": "vite"}}),
            },
        )
        assert check_document(root / "README.md", root) == []

    def test_flags_a_python_entry_point_that_is_missing(self, tmp_path):
        root = build(tmp_path, "```bash\npython run_bench.py\n```\n")
        assert codes(check_document(root / "README.md", root)) == ["missing-file"]

    def test_accepts_a_python_entry_point_that_exists(self, tmp_path):
        root = build(tmp_path, "```bash\npython app.py\n```\n", {"app.py": ""})
        assert check_document(root / "README.md", root) == []

    def test_flags_a_make_target_that_does_not_exist(self, tmp_path):
        root = build(
            tmp_path,
            "```bash\nmake deploy\n```\n",
            {"Makefile": "build:\n\techo hi\ntest:\n\techo test\n"},
        )
        findings = check_document(root / "README.md", root)
        assert codes(findings) == ["missing-make-target"]
        assert "build" in findings[0].detail

    def test_flags_a_copy_source_that_does_not_exist(self, tmp_path):
        root = build(tmp_path, "```bash\ncp .env.sample .env\n```\n")
        assert codes(check_document(root / "README.md", root)) == ["missing-file"]

    def test_accepts_a_copy_whose_source_exists(self, tmp_path):
        root = build(tmp_path, "```bash\ncp .env.example .env\n```\n", {".env.example": ""})
        assert check_document(root / "README.md", root) == []

    def test_flags_a_missing_requirements_file(self, tmp_path):
        root = build(tmp_path, "```bash\npip install -r requirements.txt\n```\n")
        assert codes(check_document(root / "README.md", root)) == ["missing-file"]

    def test_understands_prompts_and_ignores_output(self, tmp_path):
        """A console transcript mixes commands with their output."""
        root = build(
            tmp_path,
            "```console\n$ npm run dev\nserver listening on run_bench.py\n```\n",
            {"package.json": json.dumps({"scripts": {"dev": "vite"}})},
        )
        # `run_bench.py` appears only in output, so it must not be checked.
        assert check_document(root / "README.md", root) == []

    def test_ignores_comments_and_placeholders(self, tmp_path):
        root = build(
            tmp_path,
            "```bash\n# python setup.py install\npython $SCRIPT\npython <your-file>.py\n```\n",
        )
        assert check_document(root / "README.md", root) == []

    def test_handles_line_continuations(self, tmp_path):
        root = build(
            tmp_path,
            "```bash\npython \\\n  train.py\n```\n",
        )
        assert codes(check_document(root / "README.md", root)) == ["missing-file"]

    def test_never_executes_anything(self, tmp_path):
        """The headline safety property: reading, not running."""
        canary = tmp_path / "canary.txt"
        root = build(
            tmp_path,
            f"```bash\ntouch {canary}\nrm -rf /\npython evil.py\n```\n",
        )
        check_document(root / "README.md", root)
        assert not canary.exists()


# --------------------------------------------------------------------------- #
# Links, images, anchors
# --------------------------------------------------------------------------- #

class TestLinks:
    def test_flags_a_link_to_a_missing_file(self, tmp_path):
        root = build(tmp_path, "See [the guide](docs/guide.md).\n")
        assert codes(check_document(root / "README.md", root)) == ["missing-link-target"]

    def test_accepts_a_link_to_a_file_that_exists(self, tmp_path):
        root = build(tmp_path, "See [the guide](docs/guide.md).\n", {"docs/guide.md": "# Guide"})
        assert check_document(root / "README.md", root) == []

    def test_flags_a_missing_image(self, tmp_path):
        root = build(tmp_path, "![demo](docs/demo.gif)\n")
        findings = check_document(root / "README.md", root)
        assert codes(findings) == ["missing-image"]

    def test_ignores_external_urls(self, tmp_path):
        root = build(
            tmp_path,
            "[site](https://example.com) [badge](http://img.shields.io/x.svg) "
            "[mail](mailto:a@b.c) [proto](//cdn.example.com/x.png)\n",
        )
        assert check_document(root / "README.md", root) == []

    def test_flags_an_anchor_with_no_matching_heading(self, tmp_path):
        root = build(tmp_path, "# Title\n\n[jump](#instalation)\n\n## Installation\n")
        findings = check_document(root / "README.md", root)
        assert codes(findings) == ["missing-anchor"]
        # A typo'd anchor should be met with the correct one, not a shrug.
        assert "installation" in findings[0].detail

    def test_accepts_a_valid_anchor(self, tmp_path):
        root = build(tmp_path, "# Title\n\n[jump](#installation)\n\n## Installation\n")
        assert check_document(root / "README.md", root) == []

    def test_slug_matches_github_rules(self):
        assert slugify("## Free models") == "free-models"
        assert slugify("🦴 Nerd Neck") == "nerd-neck"
        assert slugify("`npm run dev` explained") == "npm-run-dev-explained"
        assert slugify("C++ / Rust") == "c--rust"

    def test_duplicate_headings_get_numbered_anchors(self, tmp_path):
        root = build(tmp_path, "## Setup\n\n## Setup\n\n[second](#setup-1)\n")
        assert check_document(root / "README.md", root) == []

    def test_does_not_read_inside_code_fences(self, tmp_path):
        """Documented syntax is an example, not a claim."""
        root = build(tmp_path, "```markdown\n[example](does/not/exist.md)\n```\n")
        assert check_document(root / "README.md", root) == []

    def test_ignores_html_comments(self, tmp_path):
        root = build(tmp_path, "<!-- [old](gone.md) -->\n\n# Title\n")
        assert check_document(root / "README.md", root) == []


# --------------------------------------------------------------------------- #
# Inline paths, with the false-positive defences
# --------------------------------------------------------------------------- #

class TestInlinePaths:
    def test_flags_a_path_that_does_not_exist(self, tmp_path):
        root = build(tmp_path, "Config lives in `src/lib/config.ts`.\n")
        assert codes(check_document(root / "README.md", root)) == ["missing-path"]

    def test_resolves_a_bare_filename_found_elsewhere(self, tmp_path):
        """`App.test.tsx` means src/App.test.tsx, and is not a lie."""
        root = build(tmp_path, "See `App.test.tsx`.\n", {"src/App.test.tsx": ""})
        assert check_document(root / "README.md", root) == []

    def test_respects_gitignore_for_generated_output(self, tmp_path):
        """A clean checkout is *supposed* to lack build artefacts."""
        root = build(
            tmp_path,
            "Built files land in `dist/index.html`.\n",
            {".gitignore": "dist/\n"},
        )
        assert check_document(root / "README.md", root) == []

    def test_gitignore_negation_is_honoured(self, tmp_path):
        root = build(
            tmp_path,
            "Results in `results/summary.md`.\n",
            {".gitignore": "results/*\n!results/summary.md\n"},
        )
        assert codes(check_document(root / "README.md", root)) == ["missing-path"]

    @pytest.mark.parametrize(
        "text", ["`npm`", "`--strict`", "`Level.ERROR`", "`3.11`", "`x = 1`", "`UPPER_CASE`"]
    )
    def test_prose_in_backticks_is_not_treated_as_a_path(self, tmp_path, text):
        root = build(tmp_path, f"Use {text} here.\n")
        assert check_document(root / "README.md", root) == []


# --------------------------------------------------------------------------- #
# License
# --------------------------------------------------------------------------- #

class TestLicense:
    def test_flags_a_claim_with_no_license_file(self, tmp_path):
        """The real bug this check exists for."""
        root = build(tmp_path, "# App\n\n## License\n\nMIT.\n")
        findings = check_document(root / "README.md", root)
        assert codes(findings) == ["missing-license-file"]
        assert findings[0].level is Level.ERROR

    def test_accepts_a_matching_license(self, tmp_path):
        root = build(
            tmp_path,
            "## License\n\nMIT\n",
            {"LICENSE": "MIT License\n\nPermission is hereby granted, free of charge, to any person"},
        )
        assert check_document(root / "README.md", root) == []

    def test_flags_a_mismatch(self, tmp_path):
        root = build(
            tmp_path,
            "## License\n\nMIT\n",
            {"LICENSE": "Apache License\nVersion 2.0, January 2004\n"},
        )
        findings = check_document(root / "README.md", root)
        assert codes(findings) == ["license-mismatch"]
        assert "Apache-2.0" in findings[0].message

    def test_says_nothing_when_the_docs_make_no_claim(self, tmp_path):
        root = build(tmp_path, "# App\n\nNo legal section here.\n")
        assert check_document(root / "README.md", root) == []


# --------------------------------------------------------------------------- #
# Suppression and discovery
# --------------------------------------------------------------------------- #

class TestSuppression:
    def test_ignore_next_line_comment(self, tmp_path):
        root = build(
            tmp_path,
            "<!-- readme-lies: ignore-next-line -->\nSee [gone](nope.md).\n",
        )
        assert check_document(root / "README.md", root) == []

    def test_ignore_file_comment(self, tmp_path):
        root = build(tmp_path, "<!-- readme-lies: ignore-file -->\n[a](x.md) [b](y.md)\n")
        assert check_document(root / "README.md", root) == []

    def test_ignore_by_code(self, tmp_path):
        root = build(tmp_path, "See [gone](nope.md).\n")
        findings, _ = check(root, ("README.md",), ignore=["missing-link-target"])
        assert findings == []

    def test_skips_dependency_directories(self, tmp_path):
        build(tmp_path, "# Root\n")
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "README.md").write_text("[x](gone.md)")
        _, documents = check(tmp_path, ("**/*.md",))
        assert all("node_modules" not in p.parts for p in documents)


class TestParser:
    def test_reports_the_line_a_problem_is_on(self, tmp_path):
        root = build(tmp_path, "# Title\n\n\n\nSee [gone](nope.md).\n")
        assert check_document(root / "README.md", root)[0].line == 5

    def test_tilde_fences(self, tmp_path):
        root = build(tmp_path, "~~~bash\nnpm run nope\n~~~\n")
        doc = parse(root / "README.md")
        assert len(doc.blocks) == 1 and doc.blocks[0].is_shell

    def test_unclosed_fence_still_parses(self, tmp_path):
        root = build(tmp_path, "```bash\npython missing.py\n")
        assert codes(check_document(root / "README.md", root)) == ["missing-file"]
