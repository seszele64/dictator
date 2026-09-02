"""Database-backed logging handler for whisper-dictate.

Provides a custom logging handler that writes log entries to the SQLite database
in addition to file-based logging. This enables structured log querying and filtering.
"""

import logging
from typing import Any

from whisper_dictate.database import Database


class DatabaseLogHandler(logging.Handler):
    """Custom logging handler that writes to SQLite database.

    This handler stores log entries in the database with level, message,
    source, timestamp, and optional metadata. It provides dual logging
    by writing to both file and database.

    Attributes:
        _db: Database instance for log storage
        _source_prefix: Prefix for log source names
    """

    def __init__(
        self,
        database: Database,
        source_prefix: str = "whisper_dictate",
    ):
        """Initialize the database log handler.

        Args:
            database: Database instance for log storage (constructed by the
                caller - setup_logging / the CLI group callback - which also
                owns closing it via this handler's close())
            source_prefix: Prefix for log source names
        """
        super().__init__()
        self._db = database
        self._source_prefix = source_prefix
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Ensure database is initialized synchronously."""
        if not self._initialized:
            self._db.initialize()
            self._initialized = True

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the database.

        This method writes logs synchronously.

        Args:
            record: Log record to emit
        """
        try:
            self._ensure_initialized()
            source = (
                f"{self._source_prefix}.{record.module}"
                if record.module
                else self._source_prefix
            )

            # Extract metadata from record if present
            metadata: dict[str, Any] | None = None
            if hasattr(record, "metadata"):
                metadata = record.metadata

            # Add extra fields to metadata
            if record.exc_info:
                metadata = metadata or {}
                metadata["exception"] = self.format(record)

            self._db.create_log(
                level=record.levelname,
                message=record.getMessage(),
                source=source,
                metadata=metadata,
            )
        except Exception:
            # Don't let logging failures break the application
            # File logging will still work
            pass

    def close(self) -> None:
        """Close the handler and cleanup resources."""
        super().close()
        if self._db:
            self._db.close()
            self._db = None
            self._initialized = False
