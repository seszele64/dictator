# Database Persistence Specification

## Purpose

This specification defines the SQLite database persistence capability of the whisper-dictate system: database initialization on first run, the recordings/transcripts/logs/state schema, schema versioning, timestamp format, performance indexes, recording and transcript storage, integrity checks, state persistence, log retention, connection management, the synchronous operation pattern, and WAL mode for crash recovery.

## Requirements

### Requirement: Database initialization on first run
The system SHALL use Python's standard library `sqlite3` (instead of `aiosqlite`) for all database operations. All operations are synchronous — no `asyncio.run()` wrappers needed.

#### Scenario: Initialize database on first run
- **WHEN** the application starts and the database file does not exist
- **THEN** the system creates the database at `~/.local/share/whisper-dictate/whisper-dictate.db` using `sqlite3.connect()` with all required tables

#### Scenario: Skip initialization when database exists
- **WHEN** the application starts and the database file already exists
- **THEN** the system opens the existing database using `sqlite3.connect()` without recreating tables

#### Scenario: Create database directory if missing
- **WHEN** the application starts and the parent directory does not exist
- **THEN** the system creates the directory structure before creating the database

---

### Requirement: Database schema: recordings table
The system SHALL use `sqlite3` library (Python standard library) for synchronous SQLite operations.

#### Scenario: Create recordings table with proper schema
- **WHEN** the database is initialized
- **THEN** the system creates a `recordings` table with the following schema:
  - `id` INTEGER PRIMARY KEY AUTOINCREMENT
  - `file_path` TEXT NOT NULL (path to audio file)
  - `timestamp` TEXT NOT NULL DEFAULT (SQLite datetime format)
  - `duration` REAL (recording duration in seconds)
  - `format` TEXT NOT NULL DEFAULT 'wav' (audio format)
  - `sample_rate` INTEGER (audio sample rate, e.g., 16000, 44100)
  - `channels` INTEGER (number of audio channels)
  - `created_at` TEXT NOT NULL DEFAULT (SQLite datetime format)

---

### Requirement: Database schema: transcripts table
The system SHALL store transcripts associated with recordings.

#### Scenario: Create transcripts table with proper schema
- **WHEN** the database is initialized
- **THEN** the system creates a `transcripts` table with the following schema:
  - `id` INTEGER PRIMARY KEY AUTOINCREMENT
  - `recording_id` INTEGER NOT NULL (foreign key to recordings.id)
  - `text` TEXT NOT NULL (transcribed text)
  - `language` TEXT (detected language code)
  - `model_used` TEXT NOT NULL DEFAULT 'whisper-1' (Whisper model identifier)
  - `confidence` REAL (Whisper confidence score 0.0-1.0)
  - `timestamp` TEXT NOT NULL DEFAULT (SQLite datetime format)
  - `created_at` TEXT NOT NULL DEFAULT (SQLite datetime format)

#### Scenario: Enforce foreign key integrity
- **WHEN** a recording is deleted
- **THEN** the system cascades deletion to associated transcripts (ON DELETE CASCADE)

---

### Requirement: Database schema: logs table
The system SHALL store application logs for debugging and auditing.

#### Scenario: Create logs table with proper schema
- **WHEN** the database is initialized
- **THEN** the system creates a `logs` table with the following schema:
  - `id` INTEGER PRIMARY KEY AUTOINCREMENT
  - `level` TEXT NOT NULL (DEBUG, INFO, WARNING, ERROR)
  - `message` TEXT NOT NULL
  - `source` TEXT (module name, e.g., `whisper_dictate.audio` - nullable for flexibility)
  - `timestamp` TEXT NOT NULL DEFAULT (SQLite datetime format)
  - `metadata_json` TEXT (optional JSON-serialized metadata)

---

### Requirement: Database schema: state table
The system SHALL provide a key-value store for persisting application state and settings.

#### Scenario: Create state table with proper schema
- **WHEN** the database is initialized
- **THEN** the system creates a `state` table with the following schema:
  - `key` TEXT PRIMARY KEY (state key identifier)
  - `value_json` TEXT NOT NULL (JSON-serialized state value)
  - `updated_at` TEXT NOT NULL DEFAULT (SQLite datetime format)

#### Scenario: Upsert state values
- **WHEN** setting a state value with a key that already exists
- **THEN** the system updates the existing value and updates the timestamp

---

### Requirement: Database schema versioning
The system SHALL track the database schema version to enable future migrations.

#### Scenario: Store schema version in database
- **WHEN** the database is initialized
- **THEN** the system stores the current schema version in a `schema_versions` table

#### Scenario: Detect schema version mismatch
- **WHEN** the application starts and the stored schema version differs from the expected version
- **THEN** the system runs necessary migration scripts to upgrade the schema

---

### Requirement: Timestamp format specification
The system SHALL use SQLite's native datetime format for all timestamp columns.

#### Scenario: Timestamp format compatibility
- **WHEN** timestamps are created using `datetime('now')`
- **THEN** the system produces timestamps in SQLite format: `YYYY-MM-DD HH:MM:SS` (e.g., `2026-03-13 15:27:50`)
- **NOTE**: This format is ISO 8601 compatible and acceptable for all timestamp requirements

---

### Requirement: Performance indexes
The system SHALL create database indexes to optimize query performance.

#### Scenario: Create indexes on initialization
- **WHEN** the database is initialized
- **THEN** the system creates the following indexes:
  - `idx_recordings_timestamp` on `recordings(timestamp)` - for time-based queries
  - `idx_transcripts_recording_id` on `transcripts(recording_id)` - for joining with recordings
  - `idx_transcripts_timestamp` on `transcripts(timestamp)` - for time-based queries
  - `idx_logs_level` on `logs(level)` - for filtering by log level
  - `idx_logs_timestamp` on `logs(timestamp)` - for time-based queries
  - `idx_logs_source` on `logs(source)` - for filtering by source module

---

### Requirement: Recording metadata storage
The system SHALL store recording metadata in the database after transcription.

#### Scenario: Store recording metadata after transcription
- **WHEN** a recording is successfully transcribed
- **THEN** the system stores the recording file path, timestamp, duration, and format in the `recordings` table

#### Scenario: Retrieve recording by ID
- **WHEN** a request is made to retrieve a recording by its ID
- **THEN** the system returns the recording metadata including file path, timestamp, and duration

#### Scenario: List all recordings with pagination
- **WHEN** a request is made to list all recordings
- **THEN** the system returns a paginated list of recordings ordered by timestamp descending

---

### Requirement: Recording duration calculation
The system SHALL calculate the actual audio file duration after recording completes.

#### Scenario: Calculate duration from audio file after recording
- **GIVEN** a recording has been created in the database with duration=NULL
- **WHEN** the recording stops and the audio file is finalized
- **THEN** the system SHALL calculate the actual duration from the audio file and update the recording entry

#### Scenario: Use soundfile to determine duration
- **WHEN** calculating recording duration
- **THEN** the system SHALL use the soundfile library to read the audio file's actual duration in seconds

---

### Requirement: Transcript storage
The system SHALL store transcripts associated with recordings in the database.

#### Scenario: Store transcript after transcription
- **WHEN** a recording is transcribed successfully
- **THEN** the system stores the transcript text, language, model used, confidence, and timestamp in the `transcripts` table linked to the recording

#### Scenario: Retrieve transcript by recording ID
- **WHEN** a request is made to retrieve a transcript by recording ID
- **THEN** the system returns the transcript text and metadata

#### Scenario: Update transcript
- **WHEN** a user updates an existing transcript
- **THEN** the system updates the transcript record with new text and records the update timestamp

---

### Requirement: Database integrity check
The system SHALL verify database integrity on startup.

#### Scenario: Run integrity check on startup
- **WHEN** the application starts
- **THEN** the system verifies all required tables exist and logs the results

#### Scenario: Handle missing tables
- **WHEN** the integrity check finds missing tables
- **THEN** the system raises a RuntimeError with details of missing tables

---

### Requirement: State persistence operations
The system SHALL provide CRUD operations for the state table.

#### Scenario: Set state value
- **WHEN** a state value is set
- **THEN** the system stores the value as JSON with automatic timestamp update

#### Scenario: Get state value
- **WHEN** a state value is requested by key
- **THEN** the system returns the deserialized JSON value or None if not found

#### Scenario: Delete state value
- **WHEN** a state value is deleted
- **THEN** the system removes the key-value pair from the state table

---

### Requirement: Log retention management
The system SHALL automatically clean up old log entries to prevent unbounded growth.

#### Scenario: Cleanup old logs
- **WHEN** cleanup is triggered (e.g., on startup or scheduled)
- **THEN** the system deletes log entries older than the configured retention period (default: 30 days)
- **AND** returns the count of deleted entries

---

### Requirement: Database connection management
The system SHALL manage sqlite3 connections synchronously with proper lifecycle handling.

#### Scenario: Singleton database instance
- **WHEN** `get_database()` is called multiple times
- **THEN** the system returns the same database instance (singleton pattern)

#### Scenario: Lazy connection initialization
- **WHEN** the database module is imported
- **THEN** no connection is created until first database operation

#### Scenario: Connection reuse across operations
- **WHEN** multiple database operations are performed
- **THEN** the system reuses the same connection for all operations

#### Scenario: Close database connection
- **WHEN** `db.close()` is called or the context manager exits
- **THEN** the system properly closes the sqlite3 connection

---

### Requirement: Synchronous operation pattern
The system SHALL provide fully synchronous database operations without async/await or `asyncio.run()` wrappers.

#### Scenario: Direct function calls work without asyncio.run()
- **WHEN** database methods are called directly (e.g., `db.get_recordings()`)
- **THEN** the operation executes synchronously and returns the result immediately

#### Scenario: No event loop required
- **WHEN** database operations are performed
- **THEN** no asyncio event loop is created or used

#### Scenario: Thread-safe connection access
- **WHEN** the database is accessed from the main thread
- **THEN** the sqlite3 connection operates correctly with proper locking if needed

---

### Requirement: WAL mode for crash recovery
The system SHALL enable WAL (Write-Ahead Logging) mode for crash recovery and data safety.

#### Scenario: Enable WAL mode on new database
- **WHEN** a new database connection is established
- **THEN** the system executes `PRAGMA journal_mode=WAL` to enable WAL mode

#### Scenario: Verify WAL mode is persistent
- **WHEN** an existing database with WAL mode is reopened
- **THEN** the system verifies `PRAGMA journal_mode` returns `wal`

#### Scenario: WAL mode provides crash recovery
- **WHEN** the application crashes or is terminated unexpectedly
- **THEN** the WAL mode ensures no data corruption and enables recovery on restart
