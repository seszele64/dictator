"""Integration tests for the post-processing database surface (schema v3).

Covers the additive migration to version 3, the processed-output columns, the
newest-processable-transcript query, the atomic processed-result write, and the
reader column coverage required by ``_row_to_dict``'s strict zip.

These are REAL SQLite tests — no sqlite3/Database mocking.
"""

import sqlite3

import pytest

from whisper_dictate.config import DatabaseConfig
from whisper_dictate.database import CURRENT_SCHEMA_VERSION, Database

PROCESSED_COLUMNS = ("processed_text", "processed_prompt", "processed_model", "processed_at")


def _transcript_columns(db: Database) -> list[str]:
    return [row[1] for row in db.fetchall("PRAGMA table_info(transcripts)")]


class TestFreshSchemaVersion3:
    """A fresh database is created at version 3 with the processed columns."""

    def test_fresh_db_reports_version_3(self, real_db):
        assert real_db._get_schema_version() == 3
        assert CURRENT_SCHEMA_VERSION == 3

    def test_fresh_transcripts_have_processed_columns(self, real_db):
        columns = _transcript_columns(real_db)
        for column in PROCESSED_COLUMNS:
            assert column in columns

    def test_processed_columns_are_nullable(self, real_db):
        info = {row[1]: row for row in real_db.fetchall("PRAGMA table_info(transcripts)")}
        for column in PROCESSED_COLUMNS:
            # notnull flag (index 3) must be 0 (nullable)
            assert info[column][3] == 0


class TestMigrationToVersion3:
    """Migration 3 is additive, per-column guarded, and idempotent."""

    def _make_v2_db(self, db_path) -> None:
        """Build a v2 database: current tables, transcripts without processed cols."""
        raw = sqlite3.connect(db_path)
        try:
            raw.executescript(
                """
                CREATE TABLE schema_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL UNIQUE,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    duration REAL,
                    format TEXT NOT NULL DEFAULT 'mp3',
                    sample_rate INTEGER,
                    channels INTEGER,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    language TEXT,
                    model_used TEXT NOT NULL DEFAULT 'whisper-1',
                    confidence REAL,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
                );
                CREATE TABLE logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    source TEXT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    metadata_json TEXT
                );
                CREATE TABLE state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO schema_versions (version) VALUES (1);
                INSERT INTO schema_versions (version) VALUES (2);
                INSERT INTO recordings (file_path, duration) VALUES ('v2.wav', 2.0);
                INSERT INTO transcripts (recording_id, text, language)
                    VALUES (1, 'v2 text', 'en');
                """
            )
            raw.commit()
        finally:
            raw.close()

    def test_v2_to_v3_adds_columns_and_preserves_rows(self, tmp_path):
        db_path = tmp_path / "v2.db"
        self._make_v2_db(db_path)

        db = Database(DatabaseConfig(path=db_path, recordings_path=tmp_path / "recordings"))
        try:
            db.initialize()
            # All migrations share one second, so read MAX(version) rather than
            # _get_schema_version() (which orders by applied_at and is
            # non-deterministic on ties).
            assert db.fetchone("SELECT MAX(version) FROM schema_versions")[0] == 3
            for column in PROCESSED_COLUMNS:
                assert column in _transcript_columns(db)
            transcript = db.get_transcript(1)
            assert transcript["text"] == "v2 text"
            assert all(transcript[column] is None for column in PROCESSED_COLUMNS)
        finally:
            db.close()

    def test_second_initialization_performs_no_ddl(self, tmp_path):
        db_path = tmp_path / "v2b.db"
        self._make_v2_db(db_path)

        db = Database(DatabaseConfig(path=db_path, recordings_path=tmp_path / "recordings"))
        try:
            db.initialize()
            db.set_processed_transcript(1, "kept", "prompt", "model")
            # Re-run the migration directly; the per-column guards must skip all
            # four ALTERs (a duplicate ADD COLUMN would raise OperationalError).
            db._run_migration(3)
            transcript = db.get_transcript(1)
            assert transcript["processed_text"] == "kept"
        finally:
            db.close()

    def test_legacy_unversioned_migrates_through_2_to_3(self, legacy_db_path):
        db = Database(DatabaseConfig(path=legacy_db_path))
        try:
            db.initialize()
            assert db.fetchone("SELECT MAX(version) FROM schema_versions")[0] == 3
            assert "updated_at" in _transcript_columns(db)
            for column in PROCESSED_COLUMNS:
                assert column in _transcript_columns(db)
            versions = [row[0] for row in db.fetchall("SELECT version FROM schema_versions ORDER BY version")]
            assert versions == [1, 2, 3]
        finally:
            db.close()


class TestGetLatestProcessableTranscript:
    """Newest non-empty transcript selection."""

    def _seed(self, db: Database, text: str, timestamp: str | None = None) -> int:
        recording_id = db.create_recording(file_path=f"{text!r}.wav")
        transcript_id = db.create_transcript(recording_id, text)
        if timestamp is not None:
            db.execute("UPDATE transcripts SET timestamp = ? WHERE id = ?", (timestamp, transcript_id))
        return transcript_id

    def test_empty_table_returns_none(self, real_db):
        assert real_db.get_latest_processable_transcript() is None

    def test_all_empty_returns_none(self, real_db):
        self._seed(real_db, "")
        self._seed(real_db, "   ")
        assert real_db.get_latest_processable_transcript() is None

    def test_newer_empty_row_is_skipped(self, real_db):
        older = self._seed(real_db, "real text", "2020-01-01 10:00:00")
        self._seed(real_db, "", "2020-01-02 10:00:00")
        result = real_db.get_latest_processable_transcript()
        assert result is not None
        assert result["id"] == older

    @pytest.mark.parametrize("whitespace", [" ", "\t", "\n\r", "\f", "\v"])
    def test_each_whitespace_only_row_is_skipped(self, real_db, whitespace):
        older = self._seed(real_db, "real text", "2020-01-01 10:00:00")
        self._seed(real_db, whitespace, "2020-01-02 10:00:00")
        result = real_db.get_latest_processable_transcript()
        assert result is not None
        assert result["id"] == older

    def test_timestamp_ordering_wins(self, real_db):
        self._seed(real_db, "ten", "2020-01-01 10:00:00")
        newest = self._seed(real_db, "eleven", "2020-01-01 11:00:00")
        result = real_db.get_latest_processable_transcript()
        assert result is not None
        assert result["id"] == newest

    def test_equal_timestamp_resolves_to_greater_id(self, real_db):
        self._seed(real_db, "first", "2020-01-01 10:00:00")
        later = self._seed(real_db, "second", "2020-01-01 10:00:00")
        result = real_db.get_latest_processable_transcript()
        assert result is not None
        assert result["id"] == later

    def test_returned_dict_has_processed_keys(self, real_db):
        self._seed(real_db, "text")
        result = real_db.get_latest_processable_transcript()
        assert result is not None
        for column in PROCESSED_COLUMNS:
            assert column in result


class TestSetProcessedTranscript:
    """Atomic processed-result write with keep-not-clear semantics."""

    def _seed(self, db: Database, text: str = "raw text") -> int:
        recording_id = db.create_recording(file_path="p.wav")
        return db.create_transcript(recording_id, text)

    def test_first_write_populates_all_four_columns(self, real_db):
        transcript_id = self._seed(real_db)
        assert real_db.set_processed_transcript(transcript_id, "Clean output", "Summarize", "gpt-4o-mini") is True
        row = real_db.get_transcript(transcript_id)
        assert row["processed_text"] == "Clean output"
        assert row["processed_prompt"] == "Summarize"
        assert row["processed_model"] == "gpt-4o-mini"
        assert row["processed_at"] is not None

    def test_second_write_overwrites_first(self, real_db):
        transcript_id = self._seed(real_db)
        real_db.set_processed_transcript(transcript_id, "First result", "prompt A", "model-a")
        real_db.set_processed_transcript(transcript_id, "Second result", "prompt B", "model-b")
        row = real_db.get_transcript(transcript_id)
        assert row["processed_text"] == "Second result"
        assert row["processed_prompt"] == "prompt B"
        assert row["processed_model"] == "model-b"

    def test_raw_text_and_updated_at_are_preserved(self, real_db):
        transcript_id = self._seed(real_db, "um so hello there")
        before = real_db.get_transcript(transcript_id)
        real_db.set_processed_transcript(transcript_id, "Hello there.", "Clean", "gpt-4o-mini")
        after = real_db.get_transcript(transcript_id)
        assert after["text"] == "um so hello there"
        assert after["updated_at"] == before["updated_at"]

    def test_unknown_id_returns_false(self, real_db):
        assert real_db.set_processed_transcript(999999, "x", "p", "m") is False

    def test_edit_after_processing_keeps_processed_columns(self, real_db):
        transcript_id = self._seed(real_db, "original")
        real_db.set_processed_transcript(transcript_id, "Old result", "Clean", "gpt-4o-mini")
        # Backdate processed_at so the edit's updated_at is strictly later.
        real_db.execute(
            "UPDATE transcripts SET processed_at = '2020-01-01 00:00:00' WHERE id = ?",
            (transcript_id,),
        )
        assert real_db.update_transcript(transcript_id, "edited") is True
        row = real_db.get_transcript(transcript_id)
        assert row["processed_text"] == "Old result"
        assert row["processed_prompt"] == "Clean"
        assert row["processed_model"] == "gpt-4o-mini"
        assert row["processed_at"] == "2020-01-01 00:00:00"
        assert row["updated_at"] > row["processed_at"]


class TestReaderColumnCoverage:
    """Every transcript reader exposes the processed columns (strict zip)."""

    def _processed_transcript(self, db: Database) -> int:
        recording_id = db.create_recording(file_path="r.wav", duration=1.0)
        transcript_id = db.create_transcript(recording_id, "reader text")
        db.set_processed_transcript(transcript_id, "processed", "prompt", "model")
        return transcript_id

    def test_get_transcript_has_processed_keys(self, real_db):
        transcript_id = self._processed_transcript(real_db)
        row = real_db.get_transcript(transcript_id)
        assert row is not None
        for column in PROCESSED_COLUMNS:
            assert column in row

    def test_get_transcript_by_recording_has_processed_keys(self, real_db):
        transcript_id = self._processed_transcript(real_db)
        row = real_db.get_transcript_by_recording(1)
        assert row is not None
        assert row["id"] == transcript_id
        for column in PROCESSED_COLUMNS:
            assert column in row

    def test_list_transcriptions_has_processed_keys(self, real_db):
        self._processed_transcript(real_db)
        rows = real_db.list_transcriptions()
        assert rows
        for column in PROCESSED_COLUMNS:
            assert column in rows[0]

    def test_get_transcription_with_recording_has_processed_keys(self, real_db):
        transcript_id = self._processed_transcript(real_db)
        row = real_db.get_transcription_with_recording(transcript_id)
        assert row is not None
        for column in PROCESSED_COLUMNS:
            assert column in row

    def test_no_value_error_on_migrated_database(self, legacy_db_path):
        db = Database(DatabaseConfig(path=legacy_db_path))
        try:
            db.initialize()
            # All four readers must not raise the strict-zip ValueError.
            assert db.get_transcript(1) is not None
            assert db.get_transcript_by_recording(1) is not None
            assert db.list_transcriptions() is not None
            assert db.get_transcription_with_recording(1) is not None
        finally:
            db.close()
