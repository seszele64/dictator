# whisper-dictate Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-09-02

## Active Technologies

- Python 3.11+ + dunstify (notifications), dunst (daemon), subprocess (for CLI)

## Project Structure

```text
src/whisper_dictate/   # src layout (landed Day 5)
tests/
openspec/          # OpenSpec changes + specs (single source of truth)
specs/             # DEPRECATED stub — see specs/README.md; do not add specs here
```

## Commands

- Test: `uv run pytest`
- Lint: `uv run ruff check .`

## Code Style

Python 3.11+: Follow standard conventions

## Recent Changes

- 001-persistent-notification: Added Python 3.11+ + dunstify (notifications), dunst (daemon), subprocess (for CLI)
- phase-1-truth (P3): archived completed OpenSpec changes; `openspec/specs/` is the single source of truth; legacy root `specs/` deprecated (see specs/README.md)

<!-- MANUAL ADDITIONS START -->

## OpenSpec Integration

OpenSpec is a spec-driven development (SDD) framework for AI coding assistants. It provides structured workflows for planning, implementing, and verifying feature changes with clear artifacts and acceptance criteria.

### Available Slash Commands

| Command | Purpose |
|---------|---------|
| `/opsx:new` | Start a new change proposal |
| `/opsx:continue` | Create the next artifact in the sequence |
| `/opsx:ff <name>` | Fast-forward all artifacts for a change |
| `/opsx:apply` | Implement tasks from the current change |
| `/opsx:verify` | Validate implementation against specs |
| `/opsx:archive` | Complete and archive the current change |
| `/opsx:sync` | Sync specs to main branch |
| `/opsx:explore` | Think through ideas and explore approaches |

### Quick Start Workflow

1. Run `/opsx:ff <change-name>` to create all planning artifacts
2. Review `proposal.md`, `specs/`, `design.md`, and `tasks.md`
3. Run `/opsx:apply <change-name>` to implement
4. Run `openspec validate <change-name>` to verify
5. Run `/opsx:archive` when complete

### Directory Structure

```
openspec/
├── changes/<change-name>/   # Change-specific artifacts
│   ├── proposal.md
│   ├── specs/
│   ├── design.md
│   └── tasks.md
└── specs/                   # Synced specification files
```

### Type checking
- `uv run mypy` — strict core gate (P7, Day 4+): must stay clean. Ratchet policy lives in `pyproject.toml` `[tool.mypy]` (strict by default for all `whisper_dictate` modules; opt-out only via explicit per-module override, never added without owner approval — currently only `cli.py`, per D3).

### Pre-commit
- `uv run pre-commit run --all-files` — local gate mirror (ruff lint+format, whitespace/EOF, YAML/TOML, merge-conflict checks); hooks pinned (ruff v0.16.1, pre-commit-hooks v6.0.0); `tests/snapshots/` excluded from file-modifying hooks.

### CI
- GitHub Actions on push/PR (`.github/workflows/ci.yml`), uv-native + SHA-pinned actions: lint (ruff check + format check), typecheck (mypy strict), test matrix 3.11/3.12/3.13, coverage job (per-module floors via `scripts/check_coverage.py` + artifact), pip-audit. Env from `uv sync --locked --extra dev` — a uv.lock/pyproject desync fails loudly.
- The 3.13 leg is `allow-fail` as a documented P10 bridge (pydub imports `audioop`, removed in 3.13; today green because conftest mocks pydub) — remove the bridge when P10 lands.
- `.github/dependabot.yml`: `github-actions` + `uv` ecosystems, weekly, grouped, 7-day cooldown.

<!-- MANUAL ADDITIONS END -->
