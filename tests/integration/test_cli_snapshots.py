"""CLI snapshot tests — the S0 characterization drift detector.

Every test records/compares a normalized capture of one CLI command (stdout,
stderr, exit code, database end-state) against a baseline JSON in
tests/snapshots/. These pin the observable behavior of the CLI through the
upcoming structural refactors (S2 singleton removal, S3 god-module splits,
S4 toggle merge): any drift fails the suite with a reviewable diff.

All tests run offline against a real SQLite database (per project convention)
with the transcription/recorder/clipboard seams replaced by the formalized
fakes from tests/fakes.py — no Mock objects at the seams under test.

Regenerate baselines (deliberately, after reviewing a diff):
    UPDATE_SNAPSHOTS=1 uv run pytest tests/integration/test_cli_snapshots.py
"""

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.helpers.snapshot import snapshot_cli
from whisper_dictate.config import AppConfig, AudioConfig, DatabaseConfig, WhisperConfig
from whisper_dictate.database import Database
from whisper_dictate.transcription import TranscriptionError

# Seed texts: one is deliberately >50 chars to pin the history list preview
# truncation ("...") behavior.
_HISTORY_SEED = [
    # (file_path, duration, transcript_text, pinned timestamp)
    ("2024/01/01/alpha.wav", 1.5, "alpha meeting notes about budgets", "2024-01-02 10:00:00"),
    (
        "2024/01/01/beta.wav",
        12.0,
        "beta standup notes with a very long transcript text that must be truncated",
        "2024-01-03 11:30:00",
    ),
    ("2024/01/01/gamma.wav", 30.25, "gamma retro notes", "2024-01-01 09:15:00"),
]

_LOG_SEED = [
    # (level, message, source, metadata, pinned timestamp)
    (
        "INFO",
        "Transcription completed",
        "dictation",
        {"recording_id": 1, "duration": 2.5, "language": "en"},
        "2024-05-01 08:00:00",
    ),
    ("ERROR", "Dictation failed: simulated API timeout", "dictation", None, "2024-05-02 09:30:00"),
    ("DEBUG", "startup", "whisper_dictate.cli", None, "2024-05-01 10:00:00"),
]


class FakeClipboard:
    """Deterministic clipboard stand-in so tests never touch real tools."""

    def __init__(self) -> None:
        self.available_tools: list[str] = ["fake-clipboard"]
        self.copied: list[str] = []

    def copy_to_clipboard(self, text: str) -> bool:
        self.copied.append(text)
        return True


@dataclass
class SnapshotContext:
    """Everything a snapshot test needs: config, seams, runner, seeding."""

    config: AppConfig
    db_path: Path
    tmp_root: Path
    runner: CliRunner
    provider: object
    recorder: object
    clipboard: FakeClipboard
    snap: object = field(default=None, repr=False)

    def seed_db(self) -> Database:
        """Open a standalone real Database for seeding (caller must close)."""
        db = Database(self.config.database)
        db.initialize()
        return db

    def seed_history(self, db: Database) -> list[tuple[int, int]]:
        """Seed three recordings/transcripts with pinned timestamps."""
        seeded = []
        for file_path, duration, text, ts in _HISTORY_SEED:
            rid = db.create_recording(
                file_path=file_path,
                duration=duration,
                format="wav",
                sample_rate=16000,
                channels=1,
            )
            tid = db.create_transcript(rid, text, language="en", model_used="whisper-1")
            # Pin the row timestamps (defaults are datetime('now')) so list
            # ordering AND the rendered dates are fully deterministic.
            db.execute("UPDATE transcripts SET timestamp = ? WHERE id = ?", (ts, tid))
            db.execute("UPDATE recordings SET timestamp = ? WHERE id = ?", (ts, rid))
            seeded.append((rid, tid))
        return seeded

    def seed_logs(self, db: Database) -> None:
        """Seed three log rows (with metadata) with pinned timestamps."""
        for level, message, source, metadata, ts in _LOG_SEED:
            db.create_log(level=level, message=message, source=source, metadata=metadata)
            db.execute("UPDATE logs SET timestamp = ? WHERE message = ?", (ts, message))


@pytest.fixture
def snapshot_ctx(env_isolator, monkeypatch, fake_provider, fake_recorder):
    """Wire an isolated CLI environment (XDG redirect + fakes at the seams).

    - env_isolator redirects XDG_DATA_HOME to tmp, so DatabaseConfig() (used
      by the `migrate` command, which builds its own default config) resolves
      to the same tmp DB path our snapshot config uses.
    - The three DictationService construction seams (AudioRecorder,
      create_transcriber, ClipboardManager) are replaced with deterministic
      fakes — the same seams the existing dictate tests patch per-instance.
    - whisper_dictate.cli.bootstrap is re-patched per invocation by the
      harness to return the real AppConfig below; the session-scoped
      setup_logging mock from conftest stays in place.
    """
    tmp_root = env_isolator
    # Same path DatabaseConfig() resolves to under the redirected XDG_DATA_HOME.
    db_path = tmp_root / "data" / "whisper-dictate" / "whisper-dictate.db"
    config = AppConfig(
        database=DatabaseConfig(
            path=db_path,
            recordings_path=tmp_root / "recordings",
            # Disk-independence: with the default 100 MB threshold, a machine
            # whose tmp fs is nearly full would render the low-disk warning
            # into dictate snapshots (a machine-dependent spurious failure).
            # 0 makes `has_space` unconditionally true so the branch can never
            # render (pydantic accepts 0; no validation constraint).
            min_free_space_mb=0,
        ),
        audio=AudioConfig(sample_rate=16000, channels=1, duration=1.0, mp3_enabled=False),
        openai=WhisperConfig(
            api_key="test-api-key",
            model="whisper-1",
            timeout=10.0,
            silence_threshold_dbfs=-50.0,
        ),
        copy_to_clipboard=True,
    )

    monkeypatch.setattr("whisper_dictate.dictation.AudioRecorder", lambda audio_config: fake_recorder)
    monkeypatch.setattr(
        "whisper_dictate.dictation.create_transcriber",
        lambda whisper_config: fake_provider,
    )
    clipboard = FakeClipboard()
    monkeypatch.setattr("whisper_dictate.dictation.ClipboardManager", lambda: clipboard)

    ctx = SnapshotContext(
        config=config,
        db_path=db_path,
        tmp_root=tmp_root,
        runner=CliRunner(),
        provider=fake_provider,
        recorder=fake_recorder,
        clipboard=clipboard,
        snap=None,
    )

    def snap(args, *, name, db_state_queries=None, config=None, db_path=None):
        return snapshot_cli(
            ctx.runner,
            args,
            name=name,
            config=config or ctx.config,
            db_path=db_path or ctx.db_path,
            tmp_root=ctx.tmp_root,
            db_state_queries=db_state_queries,
        )

    ctx.snap = snap
    return ctx


# ---------------------------------------------------------------------------
# 1. Top-level help — pins the command registry (what the CLI exposes).
# ---------------------------------------------------------------------------


def test_snapshot_top_level_help(snapshot_ctx):
    """Pins the top-level command list/option help: the toggle merge (S4) and
    any command-group reshuffle (S3) must consciously update this baseline."""
    snapshot_ctx.snap(["--help"], name="top_level_help")


# ---------------------------------------------------------------------------
# 2-3. dictate roundtrip (fake provider + fake recorder at the real seams).
# ---------------------------------------------------------------------------


def test_snapshot_dictate_success_roundtrip(snapshot_ctx):
    """Pins the full dictate roundtrip: recorder output, provider traffic, the
    success message block, and the persisted end-state (claim-first audio save
    row, transcript row, INFO log with metadata). Run-time DB stamps
    (timestamp/created_at of rows created now) normalize to <TIMESTAMP>;
    everything else — messages, counts, seeded-quality values — is literal."""
    ctx = snapshot_ctx
    ctx.snap(
        ["dictate", "--duration", "2.0"],
        name="dictate_success",
        db_state_queries={
            "recordings": (
                "SELECT file_path, duration, format, sample_rate, channels, timestamp, created_at FROM recordings"
            ),
            "transcripts": ("SELECT recording_id, text, language, model_used, confidence FROM transcripts"),
            "logs": "SELECT level, message, source, metadata_json FROM logs",
        },
    )
    # Seam traffic sanity (not part of the snapshot payload itself).
    assert ctx.recorder.calls[0].duration == 2.0
    assert ctx.provider.calls[0].audio_file.name == "fake-recording-1.wav"
    assert ctx.clipboard.copied == ["Hello from the fake provider."]
    # Temp-file cleanup: DictationService's finally block must unlink the
    # recorder's temp WAV after the roundtrip, so /tmp never leaks audio.
    assert not ctx.recorder.files_written[0].exists()


def test_snapshot_dictate_transcription_error(snapshot_ctx):
    """Pins the dictate error path: scripted provider failure must produce the
    exact stderr message, exit code 1, no lingering recording row (the
    in-progress row is cleaned up) and exactly one ERROR log."""
    ctx = snapshot_ctx
    ctx.provider.error = TranscriptionError("simulated provider outage", provider="fake")
    ctx.snap(
        ["dictate", "--duration", "2.0"],
        name="dictate_transcription_error",
        db_state_queries={
            "logs": "SELECT level, message, source, metadata_json FROM logs",
        },
    )
    # Nothing was copied to the clipboard on failure.
    assert ctx.clipboard.copied == []


# ---------------------------------------------------------------------------
# 4-6. history: empty list, seeded list (ordering + truncation), detail show.
# ---------------------------------------------------------------------------


def test_snapshot_history_list_empty(snapshot_ctx):
    """Pins the empty-history rendering and exit code on a fresh database."""
    snapshot_ctx.snap(["history", "list"], name="history_list_empty")


def test_snapshot_history_list_seeded(snapshot_ctx):
    """Pins the seeded history table: column layout, duration formatting,
    preview truncation, and timestamp-DESC ordering across seeded rows.
    The seeded 2024 timestamps appear VERBATIM in stdout and DB rows —
    normalization only erases run-time datetimes (near-now scoping), so a
    change to date rendering/format/timezone fails here instead of hiding."""
    ctx = snapshot_ctx
    db = ctx.seed_db()
    try:
        ctx.seed_history(db)
    finally:
        db.close()
    ctx.snap(
        ["history", "list"],
        name="history_list_seeded",
        db_state_queries={
            "transcripts": "SELECT id, timestamp, text FROM transcripts ORDER BY id",
            "recordings": "SELECT id, file_path, duration FROM recordings ORDER BY id",
        },
    )


def test_snapshot_history_show_detail(snapshot_ctx):
    """Pins the full detail rendering of one transcription (header block,
    pinned `📅 Date:` line with the seeded 2024 timestamp verbatim,
    duration/language/model lines, full untruncated text)."""
    ctx = snapshot_ctx
    db = ctx.seed_db()
    try:
        ctx.seed_history(db)
    finally:
        db.close()
    ctx.snap(
        ["history", "show", "2"],
        name="history_show_detail",
        db_state_queries={
            "detail": (
                "SELECT t.id, t.text, t.language, t.model_used, t.timestamp, "
                "t.confidence, r.duration, r.file_path FROM transcripts t "
                "JOIN recordings r ON r.id = t.recording_id WHERE t.id = 2"
            ),
        },
    )


# ---------------------------------------------------------------------------
# 7-8. audio cleanup pair: orphan scan display (dry-run) and real deletion.
# ---------------------------------------------------------------------------


def _seed_one_recording_with_files(ctx):
    """One DB-referenced file plus one orphan file on disk (44 bytes each)."""
    db = ctx.seed_db()
    try:
        rid = db.create_recording(file_path="2024/01/01/kept.wav", duration=2.0, format="wav")
        tid = db.create_transcript(rid, "kept recording transcript", language="en")
        db.execute(
            "UPDATE transcripts SET timestamp = '2024-02-01 12:00:00' WHERE id = ?",
            (tid,),
        )
    finally:
        db.close()
    recordings = ctx.config.database.recordings_path
    day_dir = recordings / "2024" / "01" / "01"
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "kept.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    (day_dir / "orphan.wav").write_bytes(b"RIFF" + b"\x00" * 40)


def test_snapshot_audio_cleanup_dry_run(snapshot_ctx):
    """Pins the orphan-scan display: found-count, total size line, per-file
    listing and the DRY RUN banner (colors stripped by CliRunner)."""
    ctx = snapshot_ctx
    _seed_one_recording_with_files(ctx)
    ctx.snap(
        ["audio", "cleanup"],
        name="audio_cleanup_dry_run",
        db_state_queries={
            "recordings": "SELECT id, file_path, duration FROM recordings ORDER BY id",
        },
    )


def test_snapshot_audio_cleanup_confirm(snapshot_ctx):
    """Pins the --confirm deletion output (deleted count + freed size) and
    that only the orphan file is removed from disk, the referenced file and
    DB rows survive."""
    ctx = snapshot_ctx
    _seed_one_recording_with_files(ctx)
    ctx.snap(
        ["audio", "cleanup", "--confirm"],
        name="audio_cleanup_confirm",
        db_state_queries={
            "recordings": "SELECT id, file_path, duration FROM recordings ORDER BY id",
        },
    )
    recordings = ctx.config.database.recordings_path
    assert not (recordings / "2024" / "01" / "01" / "orphan.wav").exists()
    assert (recordings / "2024" / "01" / "01" / "kept.wav").exists()


# ---------------------------------------------------------------------------
# 9. logs view (seeded rows incl. metadata rendering).
# ---------------------------------------------------------------------------


def test_snapshot_logs_list_seeded(snapshot_ctx):
    """Pins the log listing: found-count banner, pipe-delimited row layout
    with level/source padding, timestamp ordering (DESC, seeded non-insertion
    order), and the Metadata dict line."""
    ctx = snapshot_ctx
    db = ctx.seed_db()
    try:
        ctx.seed_logs(db)
    finally:
        db.close()
    ctx.snap(
        ["logs", "list"],
        name="logs_list_seeded",
        db_state_queries={
            "logs": ("SELECT level, message, source, timestamp, metadata_json FROM logs ORDER BY id"),
        },
    )


# ---------------------------------------------------------------------------
# 10-12. migrate trio.
# ---------------------------------------------------------------------------


def _isolate_legacy_files(monkeypatch, tmp_root, existing=()):
    """Point migration's module-level HOME constants at tmp (isolation)."""
    import whisper_dictate.migration as migration

    paths = {
        "LEGACY_STATE_FILE": tmp_root / "legacy-state",
        "LEGACY_PID_FILE": tmp_root / "legacy-pid",
        "LEGACY_AUDIO_FILE": tmp_root / "legacy-audio.wav",
    }
    for attr, path in paths.items():
        monkeypatch.setattr(migration, attr, path)
        if attr in existing:
            path.write_text("recording\n" if "pid" not in attr.lower() else "1\n")


def test_snapshot_migrate_fresh_db(snapshot_ctx, monkeypatch):
    """Pins `migrate` on a fresh environment with no legacy files: the skip
    message plus the migration_status row it records in the state table."""
    ctx = snapshot_ctx
    _isolate_legacy_files(monkeypatch, ctx.tmp_root, existing=())
    ctx.snap(
        ["migrate"],
        name="migrate_fresh_db",
        db_state_queries={
            "state": "SELECT key, value_json FROM state ORDER BY key",
        },
    )


def test_snapshot_migrate_status_with_legacy_files(snapshot_ctx, monkeypatch):
    """Pins `migrate --status` when legacy state/PID files exist: the
    Found/Not-found block and the migration-needed verdict (no DB writes)."""
    ctx = snapshot_ctx
    _isolate_legacy_files(monkeypatch, ctx.tmp_root, existing=("LEGACY_STATE_FILE", "LEGACY_PID_FILE"))
    ctx.snap(
        ["migrate", "--status"],
        name="migrate_status_with_legacy_files",
    )


def test_snapshot_legacy_v1_db_migrated_via_history_list(snapshot_ctx, legacy_db_path):
    """High-value pin: running a DB command against the real legacy v1
    database (tests/conftest.LEGACY_SCHEMA_SQL + seeded rows) triggers the
    v1->v2 schema migration inside Database.initialize(); the snapshot locks
    the migrated rendering AND the schema_versions end-state."""
    ctx = snapshot_ctx
    migrated_config = AppConfig(
        database=DatabaseConfig(
            path=legacy_db_path,
            recordings_path=ctx.config.database.recordings_path,
        ),
        audio=ctx.config.audio,
        openai=ctx.config.openai,
        copy_to_clipboard=True,
    )
    ctx.snap(
        ["history", "list"],
        name="legacy_v1_db_migrated",
        config=migrated_config,
        db_path=legacy_db_path,
        db_state_queries={
            "schema_versions": "SELECT version FROM schema_versions ORDER BY version",
            "transcripts": ("SELECT recording_id, text, language, updated_at IS NOT NULL FROM transcripts"),
        },
    )
