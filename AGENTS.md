# whisper-dictate Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-09-02

## Active Technologies

- Python 3.11+ + dunstify (notifications), dunst (daemon), subprocess (for CLI)

## Project Structure

```text
whisper_dictate/   # flat package at repo root (no src/ layout)
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

<!-- MANUAL ADDITIONS END -->
