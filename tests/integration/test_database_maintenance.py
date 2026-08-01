"""Group D Step 6d: Edge-case integration tests for cleanup_old_logs.

These are REAL SQLite integration tests - no mocking of sqlite3 or Database.

The cleanup SQL is::

    DELETE FROM logs WHERE timestamp < datetime('now', '-N days')

All tests use the real_db fixture (a temp SQLite file) and raw SQL where
explicit timestamps are needed.
"""

from whisper_dictate.config import DatabaseConfig


class TestCleanupOldLogs:
    """Thorough edge cases for cleanup_old_logs()."""

    def test_cleanup_deletes_logs_older_than_retention(self, real_db):
        """Only logs older than the retention window are deleted."""
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "old-one", "2020-01-01 00:00:00"),
        )
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "old-two", "2020-06-01 00:00:00"),
        )
        # A log from 10 days ago survives a 365-day retention window.
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, datetime('now', '-10 days'))",
            ("INFO", "recent"),
        )
        deleted = real_db.cleanup_old_logs(retention_days=365)
        assert deleted == 2
        remaining = real_db.query_logs()
        assert [log["message"] for log in remaining] == ["recent"]

    def test_cleanup_retention_zero_deletes_all(self, real_db):
        """retention_days=0 deletes every log with a past timestamp."""
        for index in range(3):
            real_db.execute(
                "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
                ("INFO", f"old-{index}", "2020-01-01 00:00:00"),
            )
        assert real_db.cleanup_old_logs(retention_days=0) == 3
        assert real_db.query_logs() == []

    def test_cleanup_large_retention_keeps_all(self, real_db):
        """A 100-year retention window deletes nothing."""
        real_db.create_log("INFO", "recent-one")
        real_db.create_log("ERROR", "recent-two")
        real_db.create_log("DEBUG", "recent-three")
        assert real_db.cleanup_old_logs(retention_days=36500) == 0
        assert len(real_db.query_logs()) == 3

    def test_cleanup_empty_logs_table_returns_zero(self, real_db):
        """No logs in the table means nothing to delete."""
        assert real_db.cleanup_old_logs(retention_days=30) == 0

    def test_cleanup_does_not_filter_by_level(self, real_db):
        """All old logs are deleted regardless of their level."""
        for level in ("INFO", "ERROR", "DEBUG", "WARNING"):
            real_db.execute(
                "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
                (level, f"old-{level}", "2020-01-01 00:00:00"),
            )
        assert real_db.cleanup_old_logs(retention_days=1) == 4
        assert real_db.query_logs() == []

    def test_cleanup_boundary_timestamp(self, real_db):
        """A log right at the retention boundary is deleted.

        The DELETE uses `timestamp < datetime('now', '-30 days')`, so the
        stored value must be strictly older than the boundary evaluated at
        cleanup time. We insert the boundary minus one second to make the
        test deterministic: a value inserted exactly at the boundary would
        survive whenever insert and cleanup land in the same second, because
        datetime('now') only has second precision.
        """
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, datetime('now', '-30 days', '-1 seconds'))",
            ("INFO", "boundary"),
        )
        assert real_db.cleanup_old_logs(retention_days=30) == 1
        assert real_db.query_logs() == []

    def test_cleanup_returns_correct_count_for_mixed(self, real_db):
        """5 old + 3 new logs -> 5 deleted, 3 remain."""
        for index in range(5):
            real_db.execute(
                "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
                ("INFO", f"old-{index}", "2020-01-01 00:00:00"),
            )
        for index in range(3):
            real_db.create_log("INFO", f"new-{index}")
        assert real_db.cleanup_old_logs(retention_days=1) == 5
        remaining = real_db.query_logs()
        assert len(remaining) == 3
        assert {log["message"] for log in remaining} == {"new-0", "new-1", "new-2"}

    def test_cleanup_idempotent(self, real_db):
        """Running cleanup twice deletes nothing the second time."""
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "old", "2020-01-01 00:00:00"),
        )
        assert real_db.cleanup_old_logs(retention_days=30) == 1
        assert real_db.cleanup_old_logs(retention_days=30) == 0

    def test_cleanup_with_metadata_json(self, real_db):
        """Old logs carrying metadata are deleted like any other log."""
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp, metadata_json) VALUES (?, ?, ?, ?)",
            ("ERROR", "old-with-meta", "2020-01-01 00:00:00", '{"user_id": 42}'),
        )
        assert real_db.cleanup_old_logs(retention_days=1) == 1
        assert real_db.query_logs() == []

    def test_cleanup_preserves_other_tables(self, real_db):
        """cleanup_old_logs() only touches the logs table."""
        recording_id = real_db.create_recording(file_path="keep.wav")
        transcript_id = real_db.create_transcript(recording_id, "keep me")
        real_db.set_state("app_state", {"version": 1})
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "old", "2020-01-01 00:00:00"),
        )
        assert real_db.cleanup_old_logs(retention_days=1) == 1
        # Logs are gone...
        assert real_db.query_logs() == []
        # ...but recordings, transcripts, and state are untouched.
        assert real_db.get_recording(recording_id) is not None
        assert real_db.get_transcript(transcript_id) is not None
        assert real_db.get_state("app_state") == {"version": 1}


class TestMaintenanceEdgeCases:
    """Additional cleanup_old_logs edge cases."""

    def test_cleanup_uses_config_log_retention_days_default(self, real_db):
        """cleanup_old_logs() uses its own default of 30 days.

        DatabaseConfig.log_retention_days also defaults to 30, but the
        method does NOT read it from config - it uses the parameter default.
        Either way, the effective retention when called with no arguments
        is 30 days.
        """
        # Document that the config default matches the method default.
        assert DatabaseConfig().log_retention_days == 30
        # 31 days old: older than the 30-day default -> deleted.
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, datetime('now', '-31 days'))",
            ("INFO", "old31"),
        )
        # 29 days old: within the 30-day default -> kept.
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, datetime('now', '-29 days'))",
            ("INFO", "new29"),
        )
        assert real_db.cleanup_old_logs() == 1
        remaining = real_db.query_logs()
        assert [log["message"] for log in remaining] == ["new29"]
