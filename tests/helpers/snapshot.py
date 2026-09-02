"""CLI snapshot harness — recorded baselines of CLI behavior (drift detector).

Records a normalized capture of a CLI invocation (stdout, stderr, exit code
and database end-state) into a human-readable JSON baseline under
``tests/snapshots/<name>.json``. On every later run the fresh capture is
compared byte-identically against the baseline, so any refactoring that
changes observable CLI behavior (singleton removal, god-module splits, the
toggle merge) fails loudly with a reviewable diff.

Regenerating baselines (deliberately, after reviewing a diff)::

    UPDATE_SNAPSHOTS=1 uv run pytest tests/integration/test_cli_snapshots.py

What the normalizer erases (volatile content), everything else must match:
- absolute tmp/XDG paths and repo paths -> ``<TMP>`` / ``<REPO>``
- datetimes (SQLite ``datetime('now')`` and ISO w/ microseconds) -> ``<TIMESTAMP>``
- storage date directories ``YYYY/MM/DD/`` -> ``<DATE>/``
- generated audio filenames ``YYYYMMDD_HHMMSS_<random>.wav|mp3`` -> ``<AUDIO_FILE>``
- free-disk amounts in the low-space warning -> ``<DISK_MB>``

Everything else — wording, wording order, whitespace/column padding, exit
codes, row counts, IDs, seeded values — is pinned byte-for-byte.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "snapshots"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Every table in the schema — row counts captured for each snapshot.
TABLES = ("logs", "recordings", "schema_versions", "state", "transcripts")

_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
_DATE_DIR_RE = re.compile(r"\d{4}/\d{2}/\d{2}(?=/)")
_AUDIO_FILENAME_RE = re.compile(r"\d{8}_\d{6}_[A-Za-z0-9]+\.(?:wav|mp3)")
_DISK_MB_RE = re.compile(r"only \d+ MB available")


def normalize(text: str, *, tmp_root: Path | str, repo_root: Path | str = REPO_ROOT) -> str:
    """Normalize volatile content so baselines are machine-independent."""
    # Absolute paths first (longest/most specific first to avoid partial hits).
    for root, marker in ((str(repo_root), "<REPO>"), (str(tmp_root), "<TMP>")):
        if root:
            text = text.replace(root, marker)
    text = _DATETIME_RE.sub("<TIMESTAMP>", text)
    text = _DATE_DIR_RE.sub("<DATE>", text)
    text = _AUDIO_FILENAME_RE.sub("<AUDIO_FILE>", text)
    text = _DISK_MB_RE.sub("only <DISK_MB> MB available", text)
    return text


def capture_db_state(db_path: Path, queries: dict[str, str]) -> dict[str, Any]:
    """Capture row counts for every table plus the result rows of caller SQL.

    Opens an independent read-only connection *after* the CLI invocation has
    finished (all CLI-owned connections are closed by then), so this observes
    the true end-state without interfering with the singletons under test.
    """
    if not db_path.exists():
        return {"counts": None, "queries": None}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }
        query_results = {
            name: [list(row) for row in conn.execute(sql).fetchall()]
            for name, sql in queries.items()
        }
    finally:
        conn.close()
    return {"counts": counts, "queries": query_results}


def snapshot_cli(
    runner,
    args: list[str],
    *,
    name: str,
    config,
    db_path: Path,
    tmp_root: Path,
    db_state_queries: dict[str, str] | None = None,
) -> str:
    """Run one CLI command, capture its observable behavior, compare to baseline.

    Patches ``whisper_dictate.cli.load_config`` to return the supplied real
    ``AppConfig`` (tmp paths) for the duration of the invocation. The
    session-scoped ``setup_logging`` mock from conftest stays in place, and
    logging is additionally disabled while the command runs so stderr
    contains only what the CLI itself echoes — logging-internal noise
    (e.g. the ``logging.lastResort`` handler, whose activation depends on
    pytest's logging plugin handlers) is not part of the CLI contract.

    Baselines live in ``tests/snapshots/<name>.json`` as sorted-keys,
    indent-2 JSON of the *normalized* payload. Set ``UPDATE_SNAPSHOTS=1`` to
    (re)generate. Returns the normalized capture for optional extra asserts.
    """
    from whisper_dictate.cli import cli

    payload_args = list(args)

    logging.disable(logging.CRITICAL)
    try:
        with patch(
            "whisper_dictate.cli.load_config", lambda *a, **k: config
        ):
            result = runner.invoke(cli, payload_args)
    finally:
        logging.disable(logging.NOTSET)

    stderr = ""
    try:
        stderr = result.stderr or ""
    except Exception:  # pragma: no cover - click < 8.2 mixes stderr into stdout
        stderr = ""

    payload = {
        "args": payload_args,
        "exit_code": result.exit_code,
        "exception": repr(result.exception) if result.exception is not None else None,
        "stderr": stderr,
        "stdout": result.stdout or "",
        "db": capture_db_state(db_path, dict(db_state_queries or {})),
    }

    actual = normalize(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        tmp_root=tmp_root,
    )

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    baseline_path = SNAPSHOTS_DIR / f"{name}.json"

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        baseline_path.write_text(actual, encoding="utf-8")
        return actual

    if not baseline_path.exists():
        raise AssertionError(
            f"No snapshot baseline for {name!r} at {baseline_path}.\n"
            "Run with UPDATE_SNAPSHOTS=1 to record it after reviewing the "
            "capture below:\n" + actual
        )

    expected = baseline_path.read_text(encoding="utf-8")
    if expected != actual:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile=f"expected: {baseline_path.name} (committed baseline)",
                tofile=f"actual: {name} (re-run with UPDATE_SNAPSHOTS=1 if intended)",
                lineterm="",
            )
        )
        raise AssertionError(
            f"CLI snapshot mismatch for {name!r} — observable CLI behavior "
            f"drifted from the committed baseline:\n{diff}"
        )
    return actual
