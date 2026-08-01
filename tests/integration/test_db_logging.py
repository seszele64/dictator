"""Integration tests for database-backed logging against a real SQLite database.

These tests exercise the ``DatabaseLogHandler`` and ``setup_dual_logging``
against a real SQLite database via the ``real_db`` fixture, verifying that
log records are actually persisted to the ``logs`` table.
"""

import json
import logging
import sys
from unittest.mock import patch

import pytest

from whisper_dictate.config import DatabaseConfig
from whisper_dictate.db_logging import DatabaseLogHandler, setup_dual_logging


@pytest.fixture
def restore_root_logger():
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    yield
    root.handlers = saved_handlers
    root.level = saved_level


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

    def test_handler_with_config_uses_singleton(self, real_db_config, db_singleton_reset):
        from whisper_dictate.database import get_database

        handler = DatabaseLogHandler(config=real_db_config)
        handler.emit(_make_record(logging.INFO, "singleton message"))

        db = get_database(real_db_config)
        assert handler._database is db
        rows = _query_logs(db)
        assert len(rows) == 1
        assert rows[0][1] == "singleton message"

    def test_multiple_handlers_share_singleton(self, real_db_config, db_singleton_reset):
        from whisper_dictate.database import get_database

        handler1 = DatabaseLogHandler(config=real_db_config)
        handler2 = DatabaseLogHandler(config=real_db_config)
        handler1.emit(_make_record(logging.INFO, "from handler1"))
        handler2.emit(_make_record(logging.INFO, "from handler2"))

        db = get_database(real_db_config)
        assert handler1._database is handler2._database
        assert handler1._database is db
        rows = _query_logs(db)
        assert len(rows) == 2


class TestSetupDualLoggingReal:
    """Tests for setup_dual_logging with a real database."""

    def test_setup_dual_logging_real_db(self, real_db, tmp_path, restore_root_logger):
        setup_dual_logging(database=real_db, log_file=str(tmp_path / "test.log"))
        logging.getLogger("test_logger_real_db").info("hello")

        rows = _query_logs(real_db)
        assert any("hello" in row[1] for row in rows)

        content = (tmp_path / "test.log").read_text()
        assert "hello" in content

    def test_setup_dual_logging_real_then_close(self, real_db, tmp_path, restore_root_logger):
        setup_dual_logging(database=real_db, log_file=str(tmp_path / "test.log"))
        logging.getLogger("test_logger_real_close").info("first log")

        root = logging.getLogger()
        db_handler = next(h for h in root.handlers if isinstance(h, DatabaseLogHandler))
        db_handler.close()

        # After close, the handler must not write to the configured database.
        # The handler lazily re-creates a default DB on the next emit, so point
        # that default at a throwaway DB to avoid touching the real home dir.
        with patch(
            "whisper_dictate.db_logging.DatabaseConfig",
            return_value=DatabaseConfig(
                path=tmp_path / "post_close.db",
                recordings_path=tmp_path / "post_close_recordings",
            ),
        ):
            logging.getLogger("test_logger_real_close").info("second log")

        rows = _query_logs(real_db)
        assert len(rows) == 1
        assert rows[0][1] == "first log"
