"""Group C Step 6c: Integration tests for transactions and FK cascade behavior.

These are REAL SQLite integration tests - no mocking of sqlite3 or Database.
"""

import sqlite3

import pytest

from whisper_dictate.database import Database


class TestTransactions:
    """Tests for transaction semantics and raw SQL helpers."""

    def test_transaction_commits_on_success(self, real_db):
        """Changes made inside a transaction are committed on normal exit."""
        with real_db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO recordings (file_path) VALUES (?)", ("tx.wav",)
            )
            inserted_id = cursor.lastrowid
        recording = real_db.get_recording(inserted_id)
        assert recording is not None
        assert recording["file_path"] == "tx.wav"

    def test_transaction_rolls_back_on_exception(self, real_db):
        """Changes made inside a transaction are rolled back on exception."""
        with pytest.raises(ValueError), real_db.transaction() as conn:
            conn.execute(
                "INSERT INTO recordings (file_path) VALUES (?)", ("rb.wav",)
            )
            raise ValueError("boom")
        row = real_db.fetchone(
            "SELECT id FROM recordings WHERE file_path = ?", ("rb.wav",)
        )
        assert row is None

    def test_transaction_rolls_back_on_sql_failure_midway(self, real_db):
        """A SQL error on the 2nd statement rolls back the 1st statement's work.

        Characterization for the S2 singleton-removal / S3 god-module-split
        refactors: Database.transaction() must keep its BEGIN IMMEDIATE +
        ROLLBACK semantics no matter how the failure surfaces - not only for
        Python exceptions raised by the caller (covered above) but also for
        raw sqlite3 errors raised mid-transaction. Claim-first audio saves
        (dictation._save_audio_claim_first) depend on exactly this behavior.
        """
        with pytest.raises(sqlite3.IntegrityError), real_db.transaction() as conn:
            conn.execute(
                "INSERT INTO recordings (file_path) VALUES (?)", ("first.wav",)
            )
            # 2nd statement violates the FK constraint: recordings row
            # 999999 can never exist, so this INSERT always fails.
            conn.execute(
                "INSERT INTO transcripts (recording_id, text) VALUES (999999, 'orphan')"
            )
        # The 1st statement's insert must have been rolled back as well
        assert (
            real_db.fetchone(
                "SELECT id FROM recordings WHERE file_path = ?", ("first.wav",)
            )
            is None
        )

    def test_transaction_rollback_re_raises_exception(self, real_db):
        """The exception that triggered the rollback is re-raised."""
        with pytest.raises(ValueError, match="test"), real_db.transaction() as conn:
            conn.execute(
                "INSERT INTO recordings (file_path) VALUES (?)", ("rr.wav",)
            )
            raise ValueError("test")

    def test_transaction_begin_immediate(self, real_db):
        """transaction() runs BEGIN IMMEDIATE: the write lock blocks other writers.

        The connection runs in autocommit mode, so a transaction must be
        explicitly begun. BEGIN IMMEDIATE acquires the write lock at BEGIN
        time, so a second connection cannot write while the transaction is
        open.
        """
        with real_db.connection() as conn:
            assert conn.isolation_level is None  # autocommit mode

        other = sqlite3.connect(real_db.path)
        other.execute("PRAGMA busy_timeout=0")
        try:
            with real_db.transaction() as conn:
                assert conn.in_transaction
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    other.execute(
                        "INSERT INTO recordings (file_path) VALUES ('blocked.wav')"
                    )
        finally:
            other.close()
        assert (
            real_db.fetchone(
                "SELECT id FROM recordings WHERE file_path = 'blocked.wav'"
            )
            is None
        )

    def test_execute_autocommit_mode(self, real_db):
        """db.execute() auto-commits without an explicit transaction."""
        real_db.execute(
            "INSERT INTO recordings (file_path) VALUES (?)", ("auto.wav",)
        )
        row = real_db.fetchone(
            "SELECT file_path FROM recordings WHERE file_path = ?", ("auto.wav",)
        )
        assert row == ("auto.wav",)

    def test_fetchone_returns_tuple_or_none(self, real_db):
        """fetchone() returns a tuple for a hit and None for a miss."""
        assert real_db.fetchone("SELECT 1") == (1,)
        assert real_db.fetchone("SELECT 1 WHERE 0") is None

    def test_fetchall_returns_list(self, real_db):
        """fetchall() returns a list of tuples."""
        assert real_db.fetchall("SELECT 1 UNION SELECT 2") == [(1,), (2,)]


class TestForeignKeyCascade:
    """Tests for foreign key enforcement and ON DELETE CASCADE."""

    def test_delete_recording_cascades_to_transcripts(self, real_db):
        """Deleting a recording cascades to all of its transcripts."""
        recording_id = real_db.create_recording(file_path="c1.wav")
        transcript_one = real_db.create_transcript(recording_id, "one")
        transcript_two = real_db.create_transcript(recording_id, "two")
        assert real_db.delete_recording(recording_id) is True
        assert real_db.get_transcript(transcript_one) is None
        assert real_db.get_transcript(transcript_two) is None

    def test_fk_cascade_only_with_foreign_keys_on(self, real_db):
        """PRAGMA foreign_keys is enabled at initialization, so cascades work."""
        assert real_db.fetchone("PRAGMA foreign_keys") == (1,)

    def test_create_transcript_with_deleted_recording_raises(self, real_db):
        """Creating a transcript for a deleted recording raises IntegrityError."""
        recording_id = real_db.create_recording(file_path="gone.wav")
        assert real_db.delete_recording(recording_id) is True
        with pytest.raises(sqlite3.IntegrityError):
            real_db.create_transcript(recording_id, "orphan")

    def test_cascade_does_not_affect_other_recordings(self, real_db):
        """Deleting one recording leaves other recordings and transcripts intact."""
        recording_one = real_db.create_recording(file_path="keep1.wav")
        recording_two = real_db.create_recording(file_path="keep2.wav")
        transcript_one = real_db.create_transcript(recording_one, "for r1")
        transcript_two = real_db.create_transcript(recording_two, "for r2")
        assert real_db.delete_recording(recording_one) is True
        assert real_db.get_transcript(transcript_one) is None
        assert real_db.get_recording(recording_two) is not None
        transcript_two_result = real_db.get_transcript(transcript_two)
        assert transcript_two_result is not None
        assert transcript_two_result["text"] == "for r2"


class TestConnectionLifecycle:
    """Tests for connection management on per-instance Database objects."""

    def test_connection_property_yields_valid_connection(self, real_db):
        """The connection() context manager yields a usable connection."""
        with real_db.connection() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)

    def test_database_path_property(self, real_db, real_db_config):
        """db.path matches the configured database path."""
        assert real_db.path == real_db_config.get_database_path()

    def test_separate_instances_have_separate_connections(self, real_db_config):
        """Two Database instances never share connection state."""
        first = Database(real_db_config)
        second = Database(real_db_config)
        first.initialize()
        second.initialize()
        assert first._connection is not second._connection
        first.close()
        second.close()
