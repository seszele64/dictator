"""Behavior tests for `audio cleanup --dry-run` (S1 purge item 7).

The --dry-run flag used to be defined but never read (the code derived
``actual_dry_run = not confirm``), so the flag's advertised semantics were
pinned only by snapshot baselines. These tests pin the data-driven behavior
directly:

- plain invocation and explicit --dry-run: display-only — no DB writes, no
  file deletion, exit 0;
- --confirm: actually deletes orphan files (and wins over --dry-run);
- output distinguishes "would delete" (DRY RUN banner) from "deleted".

The orphan scan itself (get_orphaned_files) is read-only, so a dry run must
leave the database byte-identical (verified here via full row counts).
"""

import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from whisper_dictate.cli import cli
from whisper_dictate.config import AppConfig, AudioConfig, DatabaseConfig, WhisperConfig
from whisper_dictate.database import Database

_TABLES = ("logs", "recordings", "schema_versions", "state", "transcripts")


def _row_counts(db_path: Path) -> dict[str, int]:
    """Full row counts through an independent read-only connection."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _TABLES}
    finally:
        conn.close()


def _seed_one_recording_with_orphan(config: AppConfig) -> tuple[Path, Path]:
    """One DB-referenced file plus one orphan file on disk (44 bytes each)."""
    db = Database(config.database)
    try:
        db.initialize()
        rid = db.create_recording(file_path="2024/01/01/kept.wav", duration=2.0, format="wav")
        db.create_transcript(rid, "kept recording transcript", language="en")
    finally:
        db.close()
    recordings = config.database.recordings_path
    day_dir = recordings / "2024" / "01" / "01"
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "kept.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    (day_dir / "orphan.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    return day_dir / "kept.wav", day_dir / "orphan.wav"


@pytest.fixture
def cleanup_env(env_isolator, monkeypatch):
    """Isolated CLI env: a REAL AppConfig pointing at tmp DB/recordings.

    The session-scoped mock_cli_setup fixture patches cli.bootstrap with a
    Mock; the cleanup command needs real paths, so this fixture re-patches it
    with the real config for the duration of each test.
    """
    tmp_root = env_isolator
    db_path = tmp_root / "data" / "whisper-dictate" / "whisper-dictate.db"
    config = AppConfig(
        database=DatabaseConfig(
            path=db_path,
            recordings_path=tmp_root / "recordings",
            min_free_space_mb=0,
        ),
        audio=AudioConfig(sample_rate=16000, channels=1, duration=1.0, mp3_enabled=False),
        openai=WhisperConfig(api_key="test-api-key", model="whisper-1"),
    )
    monkeypatch.setattr("whisper_dictate.cli.bootstrap", lambda *a, **k: config)
    return config, db_path


@pytest.mark.parametrize("args", [["audio", "cleanup"], ["audio", "cleanup", "--dry-run"]])
def test_dry_run_leaves_db_and_files_untouched(cleanup_env, args):
    """Dry run (plain or explicit) is display-only: identical DB row counts,
    files untouched, exit 0, and 'would delete' (not 'deleted') wording."""
    config, db_path = cleanup_env
    kept, orphan = _seed_one_recording_with_orphan(config)
    before = _row_counts(db_path)

    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.output
    assert _row_counts(db_path) == before, "dry run must not write to the DB"
    assert orphan.exists(), "dry run must not delete the orphan file"
    assert kept.exists()
    assert "orphan.wav" in result.output
    assert "DRY RUN" in result.output
    assert "No files were deleted" in result.output
    assert "Deleted" not in result.output


def test_confirm_deletes_orphan_only(cleanup_env):
    """--confirm deletes the orphan file, keeps the referenced file and all
    DB rows, and reports the deletion."""
    config, db_path = cleanup_env
    kept, orphan = _seed_one_recording_with_orphan(config)
    before = _row_counts(db_path)

    result = CliRunner().invoke(cli, ["audio", "cleanup", "--confirm"])

    assert result.exit_code == 0, result.output
    assert not orphan.exists()
    assert kept.exists()
    assert "Deleted 1 orphaned file(s)" in result.output
    assert _row_counts(db_path) == before


def test_confirm_wins_over_dry_run(cleanup_env):
    """Documented tie-break: an explicit --confirm deletes even when
    --dry-run is also passed (pre-existing semantics, now data-driven)."""
    config, db_path = cleanup_env
    kept, orphan = _seed_one_recording_with_orphan(config)

    result = CliRunner().invoke(cli, ["audio", "cleanup", "--dry-run", "--confirm"])

    assert result.exit_code == 0, result.output
    assert not orphan.exists()
    assert kept.exists()
    assert "Deleted 1 orphaned file(s)" in result.output
