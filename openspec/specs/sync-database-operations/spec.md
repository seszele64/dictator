# Synchronous Database Operations Specification

## Purpose

This specification defines the synchronous database layer of the whisper-dictate system using Python's standard library `sqlite3`: database initialization, WAL mode for crash recovery, connection management, schema migrations, integrity verification, CRUD operations for recordings/transcripts/logs/state, and the synchronous (non-asyncio) operation pattern.

> **Scope Note**: This spec covers the "how" — the implementation approach using sqlite3. The `002-database-persistence` spec covers the "what changed" — the specific requirements introduced by replacing aiosqlite with sqlite3. Together they form the complete specification for this migration.

## Requirements

### Requirement: Database initialization with synchronous sqlite3
The system SHALL use Python's standard library `sqlite3` for all database operations, providing a synchronous database layer.

#### Scenario: Initialize database with sqlite3 on first run
- **WHEN** the application starts and the database file does not exist
- **THEN** the system creates a connection using `sqlite3.connect()` and creates all required tables

#### Scenario: Open existing database
- **WHEN** the application starts and the database file already exists
- **THEN** the system opens the existing database file with `sqlite3.connect()`

#### Scenario: Create database directory if missing
- **WHEN** the application starts and the parent directory does not exist
- **THEN** the system creates the directory structure before creating the database file

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

---

### Requirement: Database connection management
The system SHALL manage sqlite3 connections with proper lifecycle handling.

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

### Requirement: Schema migrations
The system SHALL track and apply schema migrations using version tracking.

#### Scenario: Store schema version on initialization
- **WHEN** the database is initialized
- **THEN** the system stores the current schema version in a `schema_versions` table

#### Scenario: Run migrations when version mismatch detected
- **WHEN** the application starts and stored schema version differs from expected
- **THEN** the system executes migration scripts to upgrade the schema

#### Scenario: Migration creates all required tables
- **WHEN** schema version is 0 or missing
- **THEN** the system creates all required tables: recordings, transcripts, logs, state, schema_versions

---

### Requirement: Database integrity verification
The system SHALL verify database integrity on startup to ensure data consistency.

#### Scenario: Run integrity check on startup
- **WHEN** the application starts
- **THEN** the system executes `PRAGMA integrity_check` to verify database integrity

#### Scenario: Detect missing tables on startup
- **WHEN** the integrity check finds missing tables
- **THEN** the system raises a `RuntimeError` with details of missing tables

#### Scenario: Verify all required tables exist
- **WHEN** integrity verification runs
- **THEN** the system confirms existence of: recordings, transcripts, logs, state, schema_versions tables

---

### Requirement: Recording CRUD operations
The system SHALL provide synchronous CRUD operations for recordings.

#### Scenario: Create new recording
- **WHEN** a recording is created with file_path, timestamp, duration, format, sample_rate, channels
- **THEN** the system inserts a record into the recordings table and returns the record ID

#### Scenario: Retrieve recording by ID
- **WHEN** a request is made to retrieve a recording by ID
- **THEN** the system returns the recording with all fields: id, file_path, timestamp, duration, format, sample_rate, channels, created_at

#### Scenario: List recordings with pagination
- **WHEN** a request is made to list recordings with limit and offset
- **THEN** the system returns a list of recordings ordered by timestamp descending

#### Scenario: Update recording
- **WHEN** a recording's fields are updated
- **THEN** the system modifies the record in the database

#### Scenario: Delete recording
- **WHEN** a recording is deleted by ID
- **THEN** the system removes the record from the database (cascades to transcripts)

---

### Requirement: Transcript CRUD operations
The system SHALL provide synchronous CRUD operations for transcripts.

#### Scenario: Create transcript
- **WHEN** a transcript is created with recording_id, text, language, model_used, confidence
- **THEN** the system inserts a record into the transcripts table and returns the transcript ID

#### Scenario: Retrieve transcript by recording ID
- **WHEN** a request is made to retrieve a transcript by recording ID
- **THEN** the system returns the transcript with all fields including text, language, model_used, confidence

#### Scenario: Update transcript
- **WHEN** a transcript's text or metadata is updated
- **THEN** the system modifies the record and updates the timestamp

#### Scenario: Delete transcript
- **WHEN** a transcript is deleted by ID
- **THEN** the system removes the record from the database

---

### Requirement: Log CRUD operations
The system SHALL provide synchronous CRUD operations for application logs.

#### Scenario: Create log entry
- **WHEN** a log entry is created with level, message, source, metadata_json
- **THEN** the system inserts a record into the logs table and returns the log ID

#### Scenario: Retrieve logs with filtering
- **WHEN** logs are requested with optional level, source, or timestamp filters
- **THEN** the system returns matching log entries ordered by timestamp descending

#### Scenario: Log cleanup by age
- **WHEN** log cleanup is triggered with a retention period
- **THEN** the system deletes log entries older than the specified retention period

---

### Requirement: State CRUD operations
The system SHALL provide a key-value store for application state and settings.

#### Scenario: Set state value
- **WHEN** a state value is set with a key and JSON-serialized value
- **THEN** the system stores or updates the value in the state table with timestamp

#### Scenario: Get state value
- **WHEN** a state value is requested by key
- **THEN** the system returns the deserialized JSON value or None if not found

#### Scenario: Delete state value
- **WHEN** a state value is deleted by key
- **THEN** the system removes the key-value pair from the state table

#### Scenario: List all state keys
- **WHEN** all state keys are requested
- **THEN** the system returns a list of all key-value pairs with timestamps

---

### Requirement: Synchronous operation pattern
The system SHALL provide fully synchronous database operations without async/await.

#### Scenario: Direct function calls work without asyncio.run()
- **WHEN** database methods are called directly (e.g., `db.get_recordings()`)
- **THEN** the operation executes synchronously and returns the result immediately

#### Scenario: No event loop required
- **WHEN** database operations are performed
- **THEN** no asyncio event loop is created or used

#### Scenario: Thread-safe connection access
- **WHEN** the database is accessed from the main thread
- **THEN** the sqlite3 connection operates correctly with proper locking if needed
