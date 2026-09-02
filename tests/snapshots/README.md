# CLI snapshot baselines (S0 characterization / drift detector)

Each `<name>.json` here records the **observable behavior of one CLI command**:
`stdout`, `stderr`, `exit_code`, any exception, and the database end-state
(row counts for every table plus the result rows of per-test SQL queries) —
after normalization. The snapshot tests in
`tests/integration/test_cli_snapshots.py` compare every run against these
baselines byte-for-byte and fail with a unified diff on drift.

**Purpose:** these baselines are the safety net for the structural
refactoring roadmap (S2 singleton removal, S3 god-module splits, S4 toggle
merge). If a refactor changes what the CLI prints, its exit codes, or what it
writes to the database, a snapshot test fails even when no explicit assertion
covers the change.

## Regenerating

```bash
# Review the diff first — only then regenerate:
UPDATE_SNAPSHOTS=1 uv run pytest tests/integration/test_cli_snapshots.py
```

`UPDATE_SNAPSHOTS=1` re-records every baseline that runs under it. Treat any
baseline change in a commit as a **declared, reviewable behavior change** —
never regenerate to make a red suite green without explaining the diff.

## What normalization covers

Applied by `tests/helpers/snapshot.py::normalize` to the serialized payload:

| Volatile content                                    | Normalized to   |
| --------------------------------------------------- | --------------- |
| absolute tmp/XDG paths (pytest `tmp_path` root)     | `<TMP>`         |
| repository path                                     | `<REPO>`        |
| datetimes (`YYYY-MM-DD HH:MM:SS`, ISO w/ micros)    | `<TIMESTAMP>`   |
| storage date directories (`YYYY/MM/DD/`)            | `<DATE>/`       |
| generated audio filenames (`YYYYMMDD_HHMMSS_<rand>`) | `<AUDIO_FILE>` |
| free-disk MB in the low-space warning               | `<DISK_MB>`     |

Everything else — wording, order, whitespace/column padding, exit codes, row
counts, deterministic IDs, seeded values — is pinned byte-for-byte. Tests
seed static timestamps through the real `Database` API, so most timestamps in
the baselines are real pinned values rather than `<TIMESTAMP>` placeholders;
`<TIMESTAMP>` only appears where production code stamps "now".

## Notes

- Baselines are sorted-keys, indent-2 JSON so diffs are human-reviewable.
- `logging` is disabled while a command runs, so `stderr` contains only what
  the CLI echoes itself (`click.echo(..., err=True)`) — not logging-handler
  noise, whose activation depends on pytest's logging plugin.
- The database is captured through an independent read-only SQLite connection
  after the command finished (all CLI-owned connections are closed by then).
