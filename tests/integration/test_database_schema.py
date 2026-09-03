"""Group C Step 6a: Integration tests for database initialization, schema creation, and migrations.

These are REAL SQLite integration tests - no mocking of sqlite3 or Database.
"""

import sqlite3

import pytest

from whisper_dictate.config import DatabaseConfig
from whisper_dictate.database import CURRENT_SCHEMA_VERSION, Database


class TestDatabaseInitialization:
    """Tests for Database.initialize() and close() lifecycle."""

    def test_initialize_creates_db_file(self, real_db_config, env_isolator):
        """After initialize(), the database file exists at config.get_database_path()."""
        db = Database(real_db_config)
        assert not real_db_config.get_database_path().exists()
        db.initialize()
        assert real_db_config.get_database_path().exists()
        db.close()

    def test_initialize_creates_parent_directory(self, tmp_path, env_isolator):
        """Parent directory is created if missing (nested path)."""
        config = DatabaseConfig(
            path=tmp_path / "a" / "b" / "c" / "test.db",
            recordings_path=tmp_path / "recordings",
        )
        db = Database(config)
        db.initialize()
        assert config.get_database_path().exists()
        db.close()

    def test_initialize_is_idempotent(self, real_db_config, env_isolator):
        """Calling initialize() twice does not error and schema version stays current."""
        db = Database(real_db_config)
        db.initialize()
        db.initialize()  # second call should be a no-op
        version = db.fetchone("SELECT version FROM schema_versions ORDER BY applied_at DESC LIMIT 1")
        assert version == (CURRENT_SCHEMA_VERSION,)
        db.close()

    def test_initialize_sets_wal_mode(self, real_db_config, env_isolator):
        """PRAGMA journal_mode returns 'wal' after initialization."""
        db = Database(real_db_config)
        db.initialize()
        assert db.fetchone("PRAGMA journal_mode") == ("wal",)
        db.close()

    def test_initialize_enables_foreign_keys(self, real_db_config, env_isolator):
        """PRAGMA foreign_keys returns 1 after initialization."""
        db = Database(real_db_config)
        db.initialize()
        assert db.fetchone("PRAGMA foreign_keys") == (1,)
        db.close()

    def test_close_resets_initialized_flag(self, real_db_config):
        """After close(), _initialized is False and the db can be re-initialized."""
        db = Database(real_db_config)
        db.initialize()
        assert db._initialized is True
        db.close()
        assert db._initialized is False
        # Re-initialization works after close
        db.initialize()
        assert db._initialized is True
        version = db.fetchone("SELECT version FROM schema_versions ORDER BY applied_at DESC LIMIT 1")
        assert version == (CURRENT_SCHEMA_VERSION,)
        db.close()

    def test_close_is_idempotent(self, real_db_config):
        """Calling close() on an already-closed database does not error."""
        db = Database(real_db_config)
        db.initialize()
        db.close()
        db.close()  # should not raise


class TestSchemaCreation:
    """Tests for the database schema created on a fresh database."""

    def test_all_tables_exist(self, real_db):
        """All expected tables exist in sqlite_master after initialization."""
        tables = {row[0] for row in real_db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {"recordings", "transcripts", "logs", "state", "schema_versions"}
        assert expected <= tables

    def test_all_indexes_exist(self, real_db):
        """All expected indexes exist after initialization."""
        indexes = {row[0] for row in real_db.fetchall("SELECT name FROM sqlite_master WHERE type='index'")}
        expected = {
            "idx_recordings_timestamp",
            "idx_transcripts_recording_id",
            "idx_transcripts_timestamp",
            "idx_logs_level",
            "idx_logs_timestamp",
            "idx_logs_source",
        }
        assert expected <= indexes

    def test_schema_version_is_current(self, real_db):
        """The latest schema version row reports the current version."""
        version = real_db.fetchone("SELECT version FROM schema_versions ORDER BY applied_at DESC LIMIT 1")
        assert version == (CURRENT_SCHEMA_VERSION,)

    def test_schema_versions_table_columns(self, real_db):
        """schema_versions tracks applied migrations: (id, version, applied_at)
        with a UNIQUE constraint on version.

        Characterization for the S2-S3 persistence refactors: reshaping this
        table (column renames, dropped applied_at, lost UNIQUE) would
        silently break _get_schema_version() and every future migration
        step, and nothing else in the suite pins its shape.
        """
        info = real_db.fetchall("PRAGMA table_info(schema_versions)")
        columns = [row[1] for row in info]
        assert columns == ["id", "version", "applied_at"]
        # id is the primary key; version is a plain (non-PK) integer column
        pk_columns = [row[1] for row in info if row[5]]
        assert pk_columns == ["id"]

        # The UNIQUE constraint on version yields exactly one auto index
        unique_indexes = [row for row in real_db.fetchall("PRAGMA index_list(schema_versions)") if row[2]]
        assert len(unique_indexes) == 1
        index_columns = [row[2] for row in real_db.fetchall(f"PRAGMA index_info('{unique_indexes[0][1]}')")]
        assert index_columns == ["version"]

    def test_recordings_table_columns(self, real_db):
        """recordings has 8 columns and no updated_at column."""
        columns = [row[1] for row in real_db.fetchall("PRAGMA table_info(recordings)")]
        assert columns == [
            "id",
            "file_path",
            "timestamp",
            "duration",
            "format",
            "sample_rate",
            "channels",
            "created_at",
        ]
        assert "updated_at" not in columns

    def test_transcripts_table_columns(self, real_db):
        """transcripts has 9 columns including updated_at."""
        columns = [row[1] for row in real_db.fetchall("PRAGMA table_info(transcripts)")]
        assert columns == [
            "id",
            "recording_id",
            "text",
            "language",
            "model_used",
            "confidence",
            "timestamp",
            "created_at",
            "updated_at",
        ]

    def test_transcripts_fk_references_recordings(self, real_db):
        """transcripts has a FK to recordings with ON DELETE CASCADE."""
        fks = real_db.fetchall("PRAGMA foreign_key_list(transcripts)")
        assert len(fks) == 1
        fk = fks[0]
        # Row format: (id, seq, table, from, to, on_update, on_delete, match)
        assert fk[2] == "recordings"
        assert fk[3] == "recording_id"
        assert fk[4] == "id"
        assert fk[6] == "CASCADE"

    def test_state_primary_key_is_key(self, real_db):
        """The state table's PRIMARY KEY is the key column."""
        rows = real_db.fetchall("PRAGMA table_info(state)")
        key_row = next(row for row in rows if row[1] == "key")
        assert key_row[5] == 1  # pk flag


class TestMigration:
    """Tests for schema version tracking and migration logic."""

    def test_fresh_db_goes_directly_to_version_2(self, real_db):
        """A fresh database goes straight to the current version with one row."""
        versions = [row[0] for row in real_db.fetchall("SELECT version FROM schema_versions ORDER BY version")]
        assert versions == [CURRENT_SCHEMA_VERSION]
        assert real_db._get_schema_version() == CURRENT_SCHEMA_VERSION

    def test_migration_v1_to_v2_adds_updated_at(self, tmp_path):
        """A v1 schema (no updated_at on transcripts) migrates to add the column."""
        # Manually build a v1 schema: all tables, transcripts WITHOUT updated_at,
        # and a schema_versions row pinned at version 1.
        db_path = tmp_path / "v1.db"
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
                    FOREIGN KEY (recording_id) REFERENCES recordings(id)
                        ON DELETE CASCADE
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
                """
            )
            raw.commit()
        finally:
            raw.close()

        config = DatabaseConfig(path=db_path, recordings_path=tmp_path / "recordings")
        db = Database(config)
        try:
            # Insert a recording and transcript in the v1 schema (no updated_at column)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("INSERT INTO recordings (file_path) VALUES ('pre-migration.wav')")
                recording_id = conn.execute(
                    "SELECT id FROM recordings WHERE file_path = 'pre-migration.wav'"
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO transcripts (recording_id, text, model_used) "
                    "VALUES (?, 'pre-migration text', 'whisper-1')",
                    (recording_id,),
                )
                conn.commit()
            finally:
                conn.close()

            db._migrate()
            columns = [row[1] for row in db.fetchall("PRAGMA table_info(transcripts)")]
            assert "updated_at" in columns
            # The pre-existing transcript row should have been backfilled
            row = db.fetchone(
                "SELECT updated_at FROM transcripts WHERE recording_id = ?",
                (recording_id,),
            )
            assert row is not None
            assert row[0] != ""  # backfill set it to datetime('now')
            # After migration there may be v1 and v2 rows; version 2 must exist
            versions = db.fetchall("SELECT version FROM schema_versions")
            assert 2 in [r[0] for r in versions]
        finally:
            db.close()

    def test_get_schema_version_returns_0_for_empty_db(self, tmp_path):
        """_get_schema_version() returns 0 on a fresh connection with no tables."""
        config = DatabaseConfig(path=tmp_path / "empty.db", recordings_path=tmp_path / "recordings")
        db = Database(config)
        # Connect without running full initialization so no tables exist.
        db._connect()
        db._initialized = True
        try:
            assert db._get_schema_version() == 0
        finally:
            db.close()


class TestIntegrityCheck:
    """Tests for _check_integrity()."""

    def test_integrity_check_passes_on_valid_db(self, real_db):
        """_check_integrity() does not raise on a properly initialized db."""
        real_db._check_integrity()  # should not raise

    def test_integrity_check_raises_on_missing_table(self, real_db):
        """_check_integrity() raises RuntimeError when a table is missing."""
        real_db.execute("DROP TABLE logs")
        with pytest.raises(RuntimeError, match="Missing tables"):
            real_db._check_integrity()
