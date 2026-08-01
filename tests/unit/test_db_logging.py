"""Unit tests for the database-backed logging handler.

These tests use mocked databases (``unittest.mock.Mock``) to verify the
``DatabaseLogHandler`` and ``setup_dual_logging`` behaviors in isolation,
without touching any real SQLite file.
"""

import logging
import sys
from unittest.mock import Mock, patch

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
    level: int = logging.INFO,
    msg: str = "test message",
    module: str | None = None,
    metadata: dict | None = None,
    exc_info=None,
) -> logging.LogRecord:
    """Build a LogRecord for testing, with optional overrides."""
    record = logging.LogRecord(
        name="test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=exc_info,
    )
    if module is not None:
        record.module = module
    if metadata is not None:
        record.metadata = metadata
    return record


class TestDatabaseLogHandlerInit:
    """Tests for DatabaseLogHandler.__init__."""

    def test_init_defaults(self):
        handler = DatabaseLogHandler()
        assert handler._database is None
        assert handler._config is None
        assert handler._source_prefix == "whisper_dictate"
        assert handler._initialized is False

    def test_init_with_database(self):
        mock_db = Mock()
        handler = DatabaseLogHandler(database=mock_db)
        assert handler._database is mock_db

    def test_init_with_config(self):
        config = DatabaseConfig()
        handler = DatabaseLogHandler(config=config)
        assert handler._config is config
        assert handler._database is None

    def test_init_with_source_prefix(self):
        handler = DatabaseLogHandler(source_prefix="myapp")
        assert handler._source_prefix == "myapp"


class TestEmit:
    """Tests for DatabaseLogHandler.emit."""

    def test_emit_creates_log_with_correct_fields(self, database):
        handler = DatabaseLogHandler(database=database)
        record = _make_record()
        handler.emit(record)
        database.create_log.assert_called_once_with(
            level="INFO",
            message="test message",
            source=f"whisper_dictate.{record.module}",
            metadata=None,
        )

    def test_emit_source_prefix_when_no_module(self, database):
        handler = DatabaseLogHandler(database=database)
        record = _make_record()
        record.module = ""
        handler.emit(record)
        database.create_log.assert_called_once()
        assert database.create_log.call_args.kwargs["source"] == "whisper_dictate"

    def test_emit_with_custom_source_prefix(self, database):
        handler = DatabaseLogHandler(database=database, source_prefix="myapp")
        handler.emit(_make_record())
        source = database.create_log.call_args.kwargs["source"]
        assert source.startswith("myapp.")

    def test_emit_with_metadata_extra(self, database):
        handler = DatabaseLogHandler(database=database)
        handler.emit(_make_record(metadata={"key": "value"}))
        database.create_log.assert_called_once()
        assert database.create_log.call_args.kwargs["metadata"] == {"key": "value"}

    def test_emit_with_exc_info_adds_exception(self, database):
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()
        handler = DatabaseLogHandler(database=database)
        record = _make_record(level=logging.ERROR, msg="error occurred", exc_info=exc_info)
        handler.emit(record)
        metadata = database.create_log.call_args.kwargs["metadata"]
        assert metadata is not None
        assert "exception" in metadata

    def test_emit_swallows_db_errors(self, database):
        database.create_log.side_effect = RuntimeError("db boom")
        handler = DatabaseLogHandler(database=database)
        handler.emit(_make_record())  # must not raise

    def test_emit_swallows_initialize_errors(self, database):
        database.initialize.side_effect = RuntimeError("init boom")
        handler = DatabaseLogHandler(database=database)
        handler.emit(_make_record())  # must not raise

    def test_emit_calls_initialize_once(self, database):
        handler = DatabaseLogHandler(database=database)
        handler.emit(_make_record())
        handler.emit(_make_record())
        assert database.initialize.call_count == 1


class TestClose:
    """Tests for DatabaseLogHandler.close."""

    def test_close_closes_database(self, database):
        handler = DatabaseLogHandler(database=database)
        handler.close()
        database.close.assert_called_once()
        assert handler._database is None
        assert handler._initialized is False

    def test_close_with_no_database(self):
        handler = DatabaseLogHandler()
        handler.close()  # must not raise

    def test_close_then_emit_reinitializes(self, database):
        handler = DatabaseLogHandler(database=database)
        handler.emit(_make_record())
        handler.close()

        fresh_db = Mock()
        with patch("whisper_dictate.db_logging.get_database", return_value=fresh_db) as mock_get_database:
            handler.emit(_make_record())

        mock_get_database.assert_called_once()
        fresh_db.initialize.assert_called_once()
        fresh_db.create_log.assert_called_once()


class TestSetupDualLogging:
    """Tests for setup_dual_logging."""

    def test_setup_dual_logging_with_db(self, tmp_path, database, restore_root_logger):
        root = setup_dual_logging(database=database, log_file=str(tmp_path / "test.log"))
        assert root is logging.getLogger()
        assert len(root.handlers) == 3
        assert any(isinstance(h, logging.FileHandler) for h in root.handlers)
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
        assert any(isinstance(h, DatabaseLogHandler) for h in root.handlers)

    def test_setup_dual_logging_without_db(self, tmp_path, restore_root_logger):
        root = setup_dual_logging(log_file=str(tmp_path / "test.log"))
        assert len(root.handlers) == 2
        assert not any(isinstance(h, DatabaseLogHandler) for h in root.handlers)

    def test_setup_dual_logging_sets_level(self, tmp_path, restore_root_logger):
        root = setup_dual_logging(level="WARNING", log_file=str(tmp_path / "test.log"))
        assert root.level == logging.WARNING
        assert all(h.level == logging.WARNING for h in root.handlers)

    def test_setup_dual_logging_clears_existing_handlers(self, tmp_path, restore_root_logger):
        root = logging.getLogger()
        dummy = logging.Handler()
        root.addHandler(dummy)
        root = setup_dual_logging(log_file=str(tmp_path / "test.log"))
        assert dummy not in root.handlers

    def test_setup_dual_logging_creates_log_dir(self, tmp_path, monkeypatch, restore_root_logger):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        setup_dual_logging(log_file=None)
        expected = tmp_path / ".local" / "share" / "whisper-dictate" / "whisper-dictate.log"
        assert expected.exists()
