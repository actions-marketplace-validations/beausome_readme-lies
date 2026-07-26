# readme-lies

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](pyproject.toml)

**Your code has tests. Your docs have nothing.**

So they rot, silently. A script gets renamed and the quickstart stops working. A
file moves and three links die. A badge says MIT and there's no LICENSE file. The
README keeps making promises the repository stopped keeping, and nothing fails.

`readme-lies` checks the claims your repository can answer about itself:

```console
$ readme-lies
README.md:34 error `npm run dev` is documented, but no such script exists  [missing-script]
    package.json defines: build, preview, test
README.md:58 error the docs say this is MIT-licensed, but there is no LICENSE file  [missing-license-file]
    Without one the terms are ambiguous and default copyright applies, so nobody may legally reuse the code.
README.md:71 error `docs/architecture.md` points at a file that does not exist  [missing-link-target]

3 errors, 0 warnings in 1 document.
```

## Install

```bash
pip install readme-lies
```

Zero runtime dependencies, on purpose: a linter you add to CI shouldn't drag a
package tree — or its CVEs — into every repository that adopts it.

## The interesting part: commands are verified, never run

Executing a README's shell blocks is a remote-code-execution primitive. Reading
them is not. Most command rot is statically detectable anyway:

| Documented | Checked against |
|---|---|
| `npm run dev` | `scripts` in `package.json` (follows `cd` first) |
| `make deploy` | targets in the `Makefile` |
| `python train.py` | the filesystem |
| `cp .env.example .env` | the source file exists |
| `pip install -r requirements.txt` | that requirements file exists |
| `./scripts/setup.sh` | the script exists |

Everything else is deliberately ignored. A linter that guesses at commands it
doesn't understand produces noise, and a noisy linter gets switched off.

`cd` is tracked inside a block, so `cd frontend && npm run dev` resolves against
`frontend/package.json` rather than the repo root. Console transcripts work too —
in a `$ `-prefixed block, output lines are not mistaken for commands.

## What it checks

| Code | Level | Finds |
|---|---|---|
| `missing-script` | error | `npm`/`yarn`/`pnpm`/`bun` script that isn't defined |
| `missing-make-target` | error | `make` target with no rule |
| `missing-file` | error | a command naming a file that isn't there |
| `missing-link-target` | error | `[text](path)` pointing at nothing |
| `missing-image` | error | a screenshot or badge whose file is gone |
| `missing-anchor` | error | `#heading-link` with no such heading (suggests the nearest) |
| `missing-license-file` | error | docs claim a license, no LICENSE file |
| `license-mismatch` | error | README says MIT, LICENSE says Apache |
| `missing-path` | warning | a path in backticks that doesn't resolve |
| `missing-package-json` | warning | an npm command where there's no manifest |

Errors fail the build. Warnings don't, unless you pass `--strict`.

## Usage

```bash
readme-lies                        # check ./README.md and ./docs
readme-lies path/to/repo
readme-lies --glob 'docs/**/*.md'  # repeatable
readme-lies --ignore missing-path  # repeatable
readme-lies --strict               # warnings fail too
readme-lies --format json          # machine-readable
readme-lies --format github        # inline PR annotations
```

Exit codes: `0` clean, `1` findings, `2` usage error.

## In CI

Published on the [GitHub Marketplace](https://github.com/marketplace/actions/readme-lies):

```yaml
- name: Check the docs still tell the truth
  uses: beausome/readme-lies@v1
```

`v1` is a moving tag that follows the latest `v1.x` release, so you get fixes
without editing your workflow. Pin to an exact release (`@v0.1.2`) if you would
rather freeze it.

The Marketplace "Use latest version" button generates an exact pin instead —
GitHub always writes the newest release tag and has no way to know a moving tag
exists. Either form works; `@v1` is the one that keeps working.

Inputs, all optional:

```yaml
- uses: beausome/readme-lies@v1
  with:
    path: .                 # repository root
    strict: "true"          # fail on warnings too
    glob: |                 # one pattern per line
      docs/**/*.md
    ignore: |               # one finding code per line
      missing-path
```

Or run the CLI directly, if you would rather not depend on an Action:

```yaml
- name: Check the docs still tell the truth
  run: pipx run readme-lies --format github
```

Either way, `--format github` emits workflow commands, so findings appear as
annotations on the exact lines of the pull request.

## Silencing things

Not every finding is a bug — a README may reference a file the user is meant to
create.

```markdown
<!-- readme-lies: ignore-next-line -->
Create a `models.json` next to `providers.py`.
```

`<!-- readme-lies: ignore-file -->` skips a whole document, and `--ignore CODE`
disables a check everywhere.

## False positives are the enemy

The first version flagged `results/leaderboard.csv` and `App.test.tsx` in a real
repository. Both were wrong: the first is generated output, the second lives in
`src/`. A docs linter that cries wolf gets disabled in a week, so:

- **`.gitignore` is honoured.** Build artefacts are *supposed* to be missing.
- **Bare filenames are resolved by search.** `App.test.tsx` finds `src/App.test.tsx`.
- **Code fences are never read as claims.** Documented syntax is an example.
- **Prose in backticks is not a path.** `npm`, `--strict`, `Level.ERROR` are left alone.
- **Uncertain checks are warnings**, and warnings don't fail your build.

One judgement call remains genuinely unresolvable: a README describing files a
pipeline *will produce* looks identical to one describing files that should
already exist. Those surface as `missing-path` warnings — silence them with
`--ignore missing-path` if your docs are output-heavy.

## What it does not do

- **No external link checking.** That needs the network, goes flaky, and
  [lychee](https://github.com/lycheeverse/lychee) already does it well.
- **No command execution.** By design. There's no `--run` flag, because a docs
  linter that runs arbitrary shell on untrusted repos is a footgun, not a feature.
- **No spell checking or prose linting.** [vale](https://vale.sh) exists.

It checks one thing: whether your repository still backs up what your docs say.

## Python API

```python
from pathlib import Path
from readme_lies import check

findings, documents = check(Path("."))
for finding in findings:
    print(finding.location(Path(".")), finding.code, finding.message)
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Every test builds a throwaway repository in a temp directory, so the suite is
offline, deterministic and independent of this repo's own state. That includes a
test asserting the tool **never executes** a command it reads — the README under
test contains `rm -rf /`.

## License

MIT — see [LICENSE](LICENSE).
