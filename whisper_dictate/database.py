"""Database module for whisper-dictate.

Provides SQLite database operations using sqlite3 with:
- Connection management via context manager
- Schema versioning and migrations
- Automatic table creation on initialization
- Integrity checking on startup
"""

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from whisper_dictate.config import DatabaseConfig

logger = logging.getLogger(__name__)

# Current schema version
CURRENT_SCHEMA_VERSION = 2


class Database:
    """SQLite database manager for whisper-dictate.

    Provides connection management, schema versioning, migrations,
    and integrity checking.
    """

    def __init__(self, config: DatabaseConfig):
        """Initialize database with configuration.

        Args:
            config: Database configuration containing path settings
        """
        self._config = config
        self._db_path = config.get_database_path()
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._initialized: bool = False  # Track initialization state

    @property
    def path(self) -> Path:
        """Get the database file path.

        Returns:
            Path: Full path to the database file
        """
        return self._db_path

    def initialize(self) -> None:
        """Initialize the database (idempotent).

        Creates the database directory if it doesn't exist, establishes
        connection, and runs migrations if needed. Safe to call multiple
        times - subsequent calls are no-ops.
        """
        with self._lock:
            # Guard: Already initialized
            if self._initialized:
                logger.debug("Database already initialized, skipping initialization")
                return

            # Create database directory if it doesn't exist
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

            logger.info(f"Initializing database at {self._db_path}")

            # Connect and configure database
            self._connect()

            # Mark as initialized before _configure to prevent recursion
            # (connection() auto-initializes and _configure uses connection())
            self._initialized = True

            self._configure()

            # Run migrations
            self._migrate()

            # Verify integrity
            self._check_integrity()

            logger.info("Database initialized successfully")

    def close(self) -> None:
        """Close the database connection.

        Resets initialization state to allow re-initialization if needed.
        """
        with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None
                self._initialized = False  # Reset state
                logger.debug("Database connection closed")

    def _ensure_initialized(self) -> None:
        """Ensure database is initialized, auto-initializing if needed.

        Raises:
            RuntimeError: If database connection is not available after initialization.
        """
        if not self._initialized:
            self.initialize()

        if not self._connection:
            raise RuntimeError(
                "Database connection not available after initialization."
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection as a context manager.

        Auto-initializes if not already initialized.

        Yields:
            sqlite3.Connection: Database connection

        Raises:
            RuntimeError: If database connection is not available after initialization.
        """
        with self._lock:
            self._ensure_initialized()
            yield self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with transaction support.

        Auto-initializes if not already initialized. All operations within this
        context are atomic - if any operation fails, all changes are rolled back.

        Yields:
            sqlite3.Connection: Database connection with active transaction

        Raises:
            RuntimeError: If database connection is not available after initialization.
        """
        with self._lock:
            self._ensure_initialized()
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def execute(self, query: str, parameters: tuple = ()) -> sqlite3.Cursor:
        """Execute a query and return the cursor.

        Args:
            query: SQL query to execute
            parameters: Query parameters

        Returns:
            sqlite3.Cursor: Result cursor
        """
        with self.connection() as conn:
            return conn.execute(query, parameters)

    def executemany(self, query: str, parameters: list) -> None:
        """Execute a query with multiple parameter sets.

        Args:
            query: SQL query to execute
            parameters: List of parameter tuples
        """
        with self.connection() as conn:
            conn.executemany(query, parameters)

    def fetchone(self, query: str, parameters: tuple = ()) -> tuple | None:
        """Execute a query and fetch one result.

        Args:
            query: SQL query to execute
            parameters: Query parameters

        Returns:
            Optional[tuple]: Result row or None
        """
        with self.connection() as conn:
            cursor = conn.execute(query, parameters)
            return cursor.fetchone()

    def fetchall(self, query: str, parameters: tuple = ()) -> list[tuple]:
        """Execute a query and fetch all results.

        Args:
            query: SQL query to execute
            parameters: Query parameters

        Returns:
            list[tuple]: Result rows
        """
        with self.connection() as conn:
            cursor = conn.execute(query, parameters)
            return cursor.fetchall()

    def _connect(self) -> None:
        """Establish database connection.

        Closes any existing connection before creating a new one to
        prevent connection leaks.
        """
        # Close existing connection if present (prevents leaks)
        if self._connection:
            try:
                self._connection.close()
                logger.debug("Closed previous database connection")
            except sqlite3.Error as e:
                logger.warning(f"Error closing previous connection: {e}")

        self._connection = sqlite3.connect(
            self._db_path,
            isolation_level=None,  # Autocommit mode
            check_same_thread=False,
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")

        logger.debug("Database connection established")

    def _configure(self) -> None:
        """Configure database settings."""
        with self.connection() as conn:
            # Set busy timeout to 5 seconds
            conn.execute("PRAGMA busy_timeout=5000")
            # Enable synchronous NORMAL for better performance
            conn.execute("PRAGMA synchronous=NORMAL")

    def _check_integrity(self) -> None:
        """Verify database integrity by checking all tables exist.

        Raises:
            RuntimeError: If integrity check fails
        """
        logger.info("Running database integrity check...")

        expected_tables = [
            "schema_versions",
            "recordings",
            "transcripts",
            "logs",
            "state",
        ]

        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            rows = cursor.fetchall()
            existing_tables = {row[0] for row in rows}

        missing_tables = set(expected_tables) - existing_tables
        if missing_tables:
            raise RuntimeError(
                f"Database integrity check failed. Missing tables: {missing_tables}"
            )

        logger.info(f"Integrity check passed. Found tables: {sorted(existing_tables)}")

    def _migrate(self) -> None:
        """Run database migrations."""
        current_version = self._get_schema_version()

        if current_version == 0:
            logger.info("No schema version found. Creating initial schema...")
            self._create_schema()
            self._set_schema_version(CURRENT_SCHEMA_VERSION)
        elif current_version < CURRENT_SCHEMA_VERSION:
            logger.info(
                f"Migrating schema from version {current_version} "
                f"to {CURRENT_SCHEMA_VERSION}..."
            )
            self._run_migrations(current_version, CURRENT_SCHEMA_VERSION)
        else:
            logger.debug(f"Schema version is current: {current_version}")

    def _get_schema_version(self) -> int:
        """Get the current schema version.

        Returns:
            int: Schema version, or 0 if not set
        """
        try:
            with self.connection() as conn:
                cursor = conn.execute(
                    "SELECT version FROM schema_versions ORDER BY applied_at DESC LIMIT 1"
                )
                row = cursor.fetchone()
                return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _set_schema_version(self, version: int) -> None:
        """Set the schema version in the database.

        Args:
            version: Schema version number
        """
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO schema_versions (version) VALUES (?) "
                "ON CONFLICT(version) DO NOTHING",
                (version,),
            )
        logger.info(f"Schema version set to {version}")

    def _create_schema(self) -> None:
        """Create all database tables."""
        with self.connection() as conn:
            # Schema versions table - tracks applied migrations
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL UNIQUE,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # Recordings table - stores audio recording metadata
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    duration REAL,
                    format TEXT NOT NULL DEFAULT 'mp3',
                    sample_rate INTEGER,
                    channels INTEGER,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # Transcripts table - stores transcription results
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
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
                )
            """)

            # Logs table - stores application logs
            conn.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    source TEXT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    metadata_json TEXT
                )
            """)

            # State table - stores key-value application state
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # Create indexes for better query performance
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_recordings_timestamp "
                "ON recordings(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_transcripts_recording_id "
                "ON transcripts(recording_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_transcripts_timestamp "
                "ON transcripts(timestamp)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_source ON logs(source)")

        logger.info("Database schema created")

    def _run_migrations(self, from_version: int, to_version: int) -> None:
        """Run migrations from one version to another.

        Args:
            from_version: Current schema version
            to_version: Target schema version
        """
        # For now, we only have version 1, so this is a placeholder
        # for future migrations
        for version in range(from_version + 1, to_version + 1):
            self._run_migration(version)
            self._set_schema_version(version)

    def _run_migration(self, version: int) -> None:
        """Run a specific migration version.

        Args:
            version: Migration version to run
        """
        logger.info(f"Running migration version {version}")

        if version == 2:
            # Migration 2: Add updated_at column to transcripts table
            with self.connection() as conn:
                # Check if column exists
                cursor = conn.execute("PRAGMA table_info(transcripts)")
                columns = cursor.fetchall()
                column_names = {col[1] for col in columns}

                if "updated_at" not in column_names:
                    # SQLite doesn't support adding columns with non-constant default values
                    # So we add it with a constant default and then update
                    conn.execute(
                        "ALTER TABLE transcripts ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
                    )
                    # Now update existing rows to have proper timestamp
                    conn.execute(
                        "UPDATE transcripts SET updated_at = datetime('now') WHERE updated_at = ''"
                    )
                    logger.info("Added updated_at column to transcripts table")

        logger.info(f"Migration version {version} completed")

    # ============ Recording Operations ============

    def create_recording(
        self,
        file_path: str,
        duration: float | None = None,
        format: str = "wav",
        sample_rate: int | None = None,
        channels: int | None = None,
    ) -> int:
        """Create a new recording entry.

        Args:
            file_path: Path to the audio file
            duration: Recording duration in seconds
            format: Audio format (default: wav)
            sample_rate: Audio sample rate
            channels: Number of audio channels

        Returns:
            int: ID of the created recording
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO recordings (file_path, duration, format, sample_rate, channels)
                VALUES (?, ?, ?, ?, ?)
                """,
                (file_path, duration, format, sample_rate, channels),
            )
            return cursor.lastrowid or 0

    def get_recording(self, recording_id: int) -> dict[str, Any] | None:
        """Get a recording by ID.

        Args:
            recording_id: Recording ID

        Returns:
            Optional[dict]: Recording data or None
        """
        row = self.fetchone("SELECT * FROM recordings WHERE id = ?", (recording_id,))
        if row:
            return self._row_to_dict(
                row,
                [
                    "id",
                    "file_path",
                    "timestamp",
                    "duration",
                    "format",
                    "sample_rate",
                    "channels",
                    "created_at",
                    "updated_at",
                ],
            )
        return None

    def get_recording_with_audio_path(
        self, recording_id: int, verify_exists: bool = False
    ) -> dict[str, Any] | None:
        """Get a recording by ID with resolved absolute audio path.

        Args:
            recording_id: Recording ID
            verify_exists: If True, verify the audio file exists on filesystem

        Returns:
            Optional[dict]: Recording data with absolute_path field, or None

        Raises:
            FileNotFoundError: If verify_exists is True and file doesn't exist
        """
        from whisper_dictate.audio_storage import get_audio_storage

        recording = self.get_recording(recording_id)
        if recording:
            audio_storage = get_audio_storage(self._config)
            absolute_path = audio_storage.get_audio_path(
                recording["file_path"], verify_exists=verify_exists
            )
            recording["absolute_path"] = str(absolute_path)
        return recording

    def list_recordings(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List recordings with pagination.

        Args:
            limit: Maximum number of recordings to return
            offset: Number of recordings to skip

        Returns:
            list[dict]: List of recording data
        """
        rows = self.fetchall(
            """
            SELECT * FROM recordings
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [
            self._row_to_dict(
                row,
                [
                    "id",
                    "file_path",
                    "timestamp",
                    "duration",
                    "format",
                    "sample_rate",
                    "channels",
                    "created_at",
                    "updated_at",
                ],
            )
            for row in rows
        ]

    def delete_recording(self, recording_id: int) -> bool:
        """Delete a recording and its transcript.

        Args:
            recording_id: Recording ID

        Returns:
            bool: True if deleted, False if not found
        """
        result = self.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
        return result.rowcount > 0

    # ============ Transcript Operations ============

    def create_transcript(
        self,
        recording_id: int,
        text: str,
        language: str | None = None,
        model_used: str = "whisper-1",
        confidence: float | None = None,
    ) -> int:
        """Create a new transcript entry.

        Args:
            recording_id: ID of the recording
            text: Transcribed text
            language: Detected language
            model_used: Whisper model used
            confidence: Transcription confidence score

        Returns:
            int: ID of the created transcript
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO transcripts
                (recording_id, text, language, model_used, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (recording_id, text, language, model_used, confidence),
            )
            return cursor.lastrowid or 0

    def get_transcript(self, transcript_id: int) -> dict[str, Any] | None:
        """Get a transcript by ID.

        Args:
            transcript_id: Transcript ID

        Returns:
            Optional[dict]: Transcript data or None
        """
        row = self.fetchone("SELECT * FROM transcripts WHERE id = ?", (transcript_id,))
        if row:
            return self._row_to_dict(
                row,
                [
                    "id",
                    "recording_id",
                    "text",
                    "language",
                    "model_used",
                    "confidence",
                    "timestamp",
                    "created_at",
                    "updated_at",
                ],
            )
        return None

    def get_transcript_by_recording(
        self, recording_id: int
    ) -> dict[str, Any] | None:
        """Get transcript for a recording.

        Args:
            recording_id: Recording ID

        Returns:
            Optional[dict]: Transcript data or None
        """
        row = self.fetchone(
            "SELECT * FROM transcripts WHERE recording_id = ?", (recording_id,)
        )
        if row:
            return self._row_to_dict(
                row,
                [
                    "id",
                    "recording_id",
                    "text",
                    "language",
                    "model_used",
                    "confidence",
                    "timestamp",
                    "created_at",
                    "updated_at",
                ],
            )
        return None

    def search_transcripts(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Search transcripts by text (case-insensitive substring match).

        Args:
            query: Search query string
            limit: Maximum number of results to return

        Returns:
            list[dict]: List of matching transcript entries with recording info
        """
        search_pattern = f"%{query}%"
        rows = self.fetchall(
            """
            SELECT t.*, r.file_path, r.timestamp as recording_timestamp, r.duration
            FROM transcripts t
            JOIN recordings r ON t.recording_id = r.id
            WHERE t.text LIKE ?
            ORDER BY t.timestamp DESC
            LIMIT ?
            """,
            (search_pattern, limit),
        )
        return [
            self._row_to_dict(
                row,
                [
                    "id",
                    "recording_id",
                    "text",
                    "language",
                    "model_used",
                    "confidence",
                    "timestamp",
                    "created_at",
                    "updated_at",
                    "file_path",
                    "recording_timestamp",
                    "duration",
                ],
            )
            for row in rows
        ]

    def list_transcriptions(
        self, limit: int = 50, date: str | None = None
    ) -> list[dict[str, Any]]:
        """List transcriptions with optional date filtering and pagination.

        Args:
            limit: Maximum number of results to return
            date: Optional date filter (YYYY-MM-DD format)

        Returns:
            list[dict]: List of transcription entries with recording info
        """
        if date:
            rows = self.fetchall(
                """
                SELECT t.*, r.file_path, r.timestamp as recording_timestamp, r.duration
                FROM transcripts t
                JOIN recordings r ON t.recording_id = r.id
                WHERE date(t.timestamp) = date(?)
                ORDER BY t.timestamp DESC
                LIMIT ?
                """,
                (date, limit),
            )
        else:
            rows = self.fetchall(
                """
                SELECT t.*, r.file_path, r.timestamp as recording_timestamp, r.duration
                FROM transcripts t
                JOIN recordings r ON t.recording_id = r.id
                ORDER BY t.timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )

        return [
            self._row_to_dict(
                row,
                [
                    "id",
                    "recording_id",
                    "text",
                    "language",
                    "model_used",
                    "confidence",
                    "timestamp",
                    "created_at",
                    "updated_at",
                    "file_path",
                    "recording_timestamp",
                    "duration",
                ],
            )
            for row in rows
        ]

    def get_transcription_with_recording(
        self, transcript_id: int
    ) -> dict[str, Any] | None:
        """Get a transcript with full recording details by transcript ID.

        Args:
            transcript_id: Transcript ID

        Returns:
            Optional[dict]: Transcript data with recording info, or None
        """
        row = self.fetchone(
            """
            SELECT t.*, r.file_path, r.timestamp as recording_timestamp, r.duration
            FROM transcripts t
            JOIN recordings r ON t.recording_id = r.id
            WHERE t.id = ?
            """,
            (transcript_id,),
        )
        if row:
            return self._row_to_dict(
                row,
                [
                    "id",
                    "recording_id",
                    "text",
                    "language",
                    "model_used",
                    "confidence",
                    "timestamp",
                    "created_at",
                    "updated_at",
                    "file_path",
                    "recording_timestamp",
                    "duration",
                ],
            )
        return None

    def update_transcript(
        self,
        transcript_id: int,
        text: str,
        language: str | None = None,
    ) -> bool:
        """Update a transcript's text and optionally language.

        Args:
            transcript_id: ID of the transcript to update
            text: New transcript text
            language: Optional new language code

        Returns:
            bool: True if transcript was found and updated, False otherwise
        """
        # Build update query dynamically based on provided parameters
        if language is not None:
            query = """
                UPDATE transcripts
                SET text = ?, language = ?, updated_at = datetime('now')
                WHERE id = ?
            """
            params = (text, language, transcript_id)
        else:
            query = """
                UPDATE transcripts
                SET text = ?, updated_at = datetime('now')
                WHERE id = ?
            """
            params = (text, transcript_id)

        result = self.execute(query, params)
        return result.rowcount > 0

    # ============ Log Operations ============

    def create_log(
        self,
        level: str,
        message: str,
        source: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Create a new log entry.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR)
            message: Log message
            source: Source of the log (module name)
            metadata: Additional metadata as JSON

        Returns:
            int: ID of the created log
        """
        metadata_json = json.dumps(metadata) if metadata else None

        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO logs (level, message, source, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (level, message, source, metadata_json),
            )
            return cursor.lastrowid or 0

    def query_logs(
        self,
        level: str | None = None,
        source: str | None = None,
        from_time: str | None = None,
        to_time: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query logs with filters.

        Args:
            level: Filter by log level
            source: Filter by source
            from_time: Filter by start timestamp (ISO format)
            to_time: Filter by end timestamp (ISO format)
            limit: Maximum number of logs to return

        Returns:
            list[dict]: List of log entries
        """
        query = "SELECT * FROM logs WHERE 1=1"
        params = []

        if level:
            query += " AND level = ?"
            params.append(level.upper())
        if source:
            query += " AND source = ?"
            params.append(source)
        if from_time:
            query += " AND timestamp >= ?"
            params.append(from_time)
        if to_time:
            query += " AND timestamp <= ?"
            params.append(to_time)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.fetchall(query, tuple(params))
        return [
            self._row_to_dict(
                row, ["id", "level", "message", "source", "timestamp", "metadata_json"]
            )
            for row in rows
        ]

    # ============ State Operations ============

    def set_state(self, key: str, value: Any) -> None:
        """Set a state value.

        Args:
            key: State key
            value: State value (will be JSON serialized)
        """
        value_json = json.dumps(value)

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO state (key, value_json, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = datetime('now')
                """,
                (key, value_json),
            )

    def get_state(self, key: str) -> Any | None:
        """Get a state value.

        Args:
            key: State key

        Returns:
            Optional[Any]: State value or None
        """
        row = self.fetchone("SELECT value_json FROM state WHERE key = ?", (key,))
        if row:
            return json.loads(row[0])
        return None

    def delete_state(self, key: str) -> bool:
        """Delete a state value.

        Args:
            key: State key

        Returns:
            bool: True if deleted, False if not found
        """
        result = self.execute("DELETE FROM state WHERE key = ?", (key,))
        return result.rowcount > 0

    # ============ Log Retention ============

    def cleanup_old_logs(self, retention_days: int = 30) -> int:
        """Delete log entries older than the retention period.

        Args:
            retention_days: Number of days to retain logs

        Returns:
            int: Number of deleted log entries
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM logs
                WHERE timestamp < datetime('now', ?)
                """,
                (f"-{retention_days} days",),
            )
            deleted = cursor.rowcount

        if deleted > 0:
            logger.info(
                f"Cleaned up {deleted} old log entries (retention: {retention_days} days)"
            )

        return deleted

    # ============ Utility Methods ============

    @staticmethod
    def _row_to_dict(row: tuple, columns: list[str]) -> dict[str, Any]:
        """Convert a database row to a dictionary.

        Args:
            row: Database row
            columns: Column names

        Returns:
            dict: Row as dictionary
        """
        return dict(zip(columns, row, strict=False))


# Global database instance
_database: Database | None = None


def get_database(config: DatabaseConfig | None = None) -> Database:
    """Get or create the global database instance.

    Args:
        config: Optional database configuration

    Returns:
        Database: Database instance
    """
    global _database

    if _database is None:
        if config is None:
            config = DatabaseConfig()
        _database = Database(config)

    return _database


def initialize_database(config: DatabaseConfig | None = None) -> Database:
    """Initialize the database.

    Args:
        config: Optional database configuration

    Returns:
        Database: Initialized database instance
    """
    db = get_database(config)
    db.initialize()
    return db


def close_database() -> None:
    """Close the global database connection.

    This should be called during application shutdown to ensure
    all database connections are properly closed.
    """
    global _database

    if _database is not None:
        _database.close()
        _database = None
        logger.debug("Global database connection closed")
