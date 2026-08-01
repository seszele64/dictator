"""Database-backed logging handler for whisper-dictate.

Provides a custom logging handler that writes log entries to the SQLite database
in addition to file-based logging. This enables structured log querying and filtering.
"""

import logging
from typing import Any

from whisper_dictate.config import DatabaseConfig
from whisper_dictate.database import Database, get_database


class DatabaseLogHandler(logging.Handler):
    """Custom logging handler that writes to SQLite database.

    This handler stores log entries in the database with level, message,
    source, timestamp, and optional metadata. It provides dual logging
    by writing to both file and database.

    Attributes:
        _database: Database instance for log storage
        _source_prefix: Prefix for log source names
    """

    def __init__(
        self,
        database: Database | None = None,
        config: DatabaseConfig | None = None,
        source_prefix: str = "whisper_dictate",
    ):
        """Initialize the database log handler.

        Args:
            database: Optional database instance (will create if not provided)
            config: Optional database configuration
            source_prefix: Prefix for log source names
        """
        super().__init__()
        self._database = database
        self._config = config
        self._source_prefix = source_prefix
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Ensure database is initialized synchronously."""
        if not self._initialized:
            if self._database is None:
                if self._config is None:
                    self._config = DatabaseConfig()
                self._database = get_database(self._config)
            self._database.initialize()
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

            self._database.create_log(
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
        if self._database:
            self._database.close()
            self._database = None
            self._initialized = False


def setup_dual_logging(
    level: str = "INFO",
    database: Database | None = None,
    config: DatabaseConfig | None = None,
    log_file: str | None = None,
) -> logging.Logger:
    """Setup dual logging (file + database).

    This function configures logging to write to both file and database,
    providing both persistent file logs for debugging and database logs
    for structured querying.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        database: Optional database instance
        config: Optional database configuration
        log_file: Optional custom log file path

    Returns:
        logging.Logger: Configured root logger
    """
    from pathlib import Path

    # Create log directory
    if log_file:
        log_path = Path(log_file)
    else:
        log_dir = Path.home() / ".local" / "share" / "whisper-dictate"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "whisper-dictate.log"

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # File handler
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(getattr(logging, level.upper()))
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, level.upper()))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Database handler (if database is available)
    if database or config:
        db_handler = DatabaseLogHandler(database=database, config=config)
        db_handler.setLevel(getattr(logging, level.upper()))
        db_handler.setFormatter(formatter)
        root_logger.addHandler(db_handler)

    return root_logger
