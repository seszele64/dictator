# Structured Logging Specification

## Purpose

This specification defines the structured logging capability of the whisper-dictate system: dual logging to file and database, structured database log entries with level/source/metadata, querying and filtering logs via the CLI, log export, and automatic log retention. It also documents the database lifecycle pattern that all database-using CLI commands must follow.

## Requirements

### Requirement: Dual logging (file + database)
The system SHALL write logs to BOTH file (stderr/stdout fallback) AND database for reliability.

#### Scenario: Log to both file and database on each log call
- **WHEN** the application logs a message at any level
- **THEN** the system writes the log to the standard file handler (stderr/stdout) AND stores a copy in the database with level, message, source, timestamp, and optional metadata

#### Scenario: Ensure log persistence even if database fails
- **WHEN** database logging fails but file logging succeeds
- **THEN** the system continues operating without interruption, ensuring critical logs are not lost

---

### Requirement: Database logging
The system SHALL store application logs in the database for structured querying.

#### Scenario: Log to database on each log call
- **WHEN** the application logs a message at any level
- **THEN** the system stores the log entry in the database with level, message, source, timestamp, and optional metadata

#### Scenario: Include source module in log entry
- **WHEN** a log entry is created
- **THEN** the system records the source module (e.g., `whisper_dictate.audio`) that generated the log

#### Scenario: Store structured metadata with log
- **WHEN** logging with additional context data
- **THEN** the system serializes the metadata as JSON and stores it in the log entry

---

### Requirement: Query logs from database
The system SHALL provide a command to query and display logs.

#### Scenario: View recent logs
- **WHEN** the user runs the `logs` command
- **THEN** the system displays recent log entries with timestamp, level, source, and message

#### Scenario: Filter logs by level
- **WHEN** the user runs `logs --level ERROR`
- **THEN** the system displays only log entries at the specified level (DEBUG, INFO, WARNING, ERROR)

#### Scenario: Filter logs by source
- **WHEN** the user runs `logs --source whisper_dictate.transcription`
- **THEN** the system displays only log entries from that source module

#### Scenario: Filter logs by date range
- **WHEN** the user runs `logs --from YYYY-MM-DD --to YYYY-MM-DD`
- **THEN** the system displays only log entries within that date range

#### Scenario: Limit log results
- **WHEN** the user runs `logs --limit N`
- **THEN** the system displays only the N most recent log entries

---

### Requirement: Export logs
The system SHALL provide functionality to export logs.

#### Scenario: Export logs to file
- **WHEN** the user runs `logs export <filename>`
- **THEN** the system exports the filtered log entries to the specified file in text format

---

### Requirement: Log retention
The system SHALL manage log retention automatically.

#### Scenario: Auto-cleanup old logs
- **WHEN** the application starts and log retention is configured
- **THEN** the system deletes log entries older than the configured retention period (default: 30 days)

#### Scenario: Configure log retention
- **WHEN** the user sets a log retention period
- **THEN** the system respects the configured period and cleans up accordingly

---

## Database Lifecycle Requirements

All CLI commands that interact with the database MUST follow the database lifecycle pattern:

### Required Pattern

1. **Initialization**: Call `asyncio.run(db.initialize())` before any database operations
2. **Cleanup**: Call `asyncio.run(db.close())` in a `finally` block after operations complete

### Implementation Options (in priority order)

1. **Preferred**: Use the `@with_database` decorator from `whisper_dictate.cli_helpers`
2. **Alternative**: Manual try/finally pattern (if decorator insufficient)

### Example

```python
@cli.command()
@with_database
@click.pass_context
def command_name(ctx, ...):
    db = ctx.obj['db']
    results = asyncio.run(db.some_query())
```

### Verification

- All database-using CLI commands must include `db.close()` in their execution path
- Commands should not hang on exit after completion
- Commands must call `initialize()` before querying
