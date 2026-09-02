"""Integration tests for database-backed logging against a real SQLite database.

These tests exercise the ``DatabaseLogHandler`` against a real SQLite database
via the ``real_db`` fixture, verifying that log records are actually persisted
to the ``logs`` table.
"""

import json
import logging
import sys

from whisper_dictate.db_logging import DatabaseLogHandler


def _make_record(
    level: int,
    msg: str,
    metadata: dict | None = None,
    exc_info=None,
) -> logging.LogRecord:
    """Build a LogRecord for testing, with optional metadata/exc_info."""
    record = logging.LogRecord(
        name="test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=exc_info,
    )
    if metadata is not None:
        record.metadata = metadata
    return record


def _query_logs(db) -> list[tuple]:
    """Fetch all rows from the logs table, oldest first."""
    with db.connection() as conn:
        return conn.execute(
            "SELECT level, message, source, metadata_json, timestamp FROM logs ORDER BY id"
        ).fetchall()


class TestDatabaseLogHandlerEmitReal:
    """Tests for DatabaseLogHandler.emit against a real database."""

    def test_emit_persists_to_real_db(self, real_db):
        handler = DatabaseLogHandler(database=real_db)
        handler.emit(_make_record(logging.INFO, "real db message"))

        rows = _query_logs(real_db)
        assert len(rows) == 1
        level, message, source, metadata_json, timestamp = rows[0]
        assert level == "INFO"
        assert message == "real db message"
        assert source.startswith("whisper_dictate.")
        assert timestamp

    def test_emit_persists_warning_level(self, real_db):
        handler = DatabaseLogHandler(database=real_db)
        handler.emit(_make_record(logging.WARNING, "warning message"))

        rows = _query_logs(real_db)
        assert len(rows) == 1
        assert rows[0][0] == "WARNING"
        assert rows[0][1] == "warning message"

    def test_emit_persists_error_level(self, real_db):
        handler = DatabaseLogHandler(database=real_db)
        handler.emit(_make_record(logging.ERROR, "error message"))

        rows = _query_logs(real_db)
        assert len(rows) == 1
        assert rows[0][0] == "ERROR"
        assert rows[0][1] == "error message"

    def test_emit_with_metadata_persists(self, real_db):
        handler = DatabaseLogHandler(database=real_db)
        handler.emit(_make_record(logging.INFO, "with metadata", metadata={"request_id": "abc"}))

        rows = _query_logs(real_db)
        metadata_json = rows[0][3]
        assert metadata_json is not None
        parsed = json.loads(metadata_json)
        assert "request_id" in parsed

    def test_emit_with_exc_info_persists_exception(self, real_db):
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
        handler = DatabaseLogHandler(database=real_db)
        handler.emit(_make_record(logging.ERROR, "error occurred", exc_info=exc_info))

        rows = _query_logs(real_db)
        metadata_json = rows[0][3]
        assert metadata_json is not None
        parsed = json.loads(metadata_json)
        assert "exception" in parsed


class TestDatabaseLogHandlerLifecycleReal:
    """Tests for DatabaseLogHandler lifecycle against a real database."""

    def test_close_then_reopen_real_db(self, real_db, real_db_config, db_singleton_reset):
        from whisper_dictate.database import Database

        handler = DatabaseLogHandler(database=real_db)
        handler.emit(_make_record(logging.INFO, "first message"))
        handler.close()

        # Reopen the same underlying DB file with a fresh Database instance.
        fresh_db = Database(real_db_config)
        fresh_handler = DatabaseLogHandler(database=fresh_db)
        fresh_handler.emit(_make_record(logging.INFO, "second message"))
        fresh_handler.close()

        rows = _query_logs(real_db)
        assert len(rows) == 2
        assert rows[0][1] == "first message"
        assert rows[1][1] == "second message"

    def test_handler_with_database_writes_rows(self, real_db, real_db_config):
        handler = DatabaseLogHandler(database=real_db)
        handler.emit(_make_record(logging.INFO, "singleton message"))

        rows = _query_logs(real_db)
        assert handler._db is real_db
        assert len(rows) == 1
        assert rows[0][1] == "singleton message"

    def test_multiple_handlers_each_own_their_database(
        self, real_db_config, tmp_path
    ):
        """Per-invocation instances: two handlers constructed with separate
        Database instances write through their own connections to their own
        files."""
        from whisper_dictate.config import DatabaseConfig
        from whisper_dictate.database import Database

        db1 = Database(real_db_config)
        db2 = Database(
            DatabaseConfig(
                path=tmp_path / "other.db",
                recordings_path=real_db_config.recordings_path,
            )
        )
        handler1 = DatabaseLogHandler(database=db1)
        handler2 = DatabaseLogHandler(database=db2)
        handler1.emit(_make_record(logging.INFO, "from handler1"))
        handler2.emit(_make_record(logging.INFO, "from handler2"))

        assert handler1._db is not handler2._db
        assert real_db_config.get_database_path().exists()
        assert (tmp_path / "other.db").exists()
        rows1 = _query_logs(db1)
        assert len(rows1) == 1
        assert rows1[0][1] == "from handler1"
        rows2 = _query_logs(db2)
        assert len(rows2) == 1
        assert rows2[0][1] == "from handler2"
        db1.close()
        db2.close()
