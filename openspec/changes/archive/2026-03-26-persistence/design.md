## Context

The whisper-dictate application currently lacks persistent storage. Audio recordings are deleted after transcription, and there is no database for storing metadata, transcripts, logs, or application state. The application uses simple file-based logging to `~/.local/share/whisper-dictate/whisper-dictate.log`.

This design addresses the need for comprehensive persistence by implementing:
- SQLite database for structured data storage
- Filesystem storage for audio recordings
- CLI commands for history and logs
- Migration path from existing state files

## Goals / Non-Goals

**Goals:**
- Implement SQLite database for storing metadata, transcripts, logs, and application state
- Create filesystem storage for audio recordings organized by date
- Add CLI commands for viewing transcription history and application logs
- Provide database-backed logging with structured log entries
- Migrate existing configuration/state from JSON files to database

**Non-Goals:**
- Cloud sync or multi-device synchronization
- Real-time streaming of audio to storage
- User authentication or access control
- Web interface or API for remote access

## Decisions

### 1. Database: SQLite with aiosqlite for async operations

**Decision**: Use `aiosqlite` for async database operations.

**Rationale**:
- Python's `sqlite3` is synchronous, which would block the event loop during recording/transcription
- `aiosqlite` provides async support that integrates well with the existing async patterns
- SQLite is sufficient for single-user local application (no multi-user conflicts expected)

**Alternatives Considered**:
- `SQLAlchemy` with async support - adds complexity for simple local storage needs
- `tinydb` - NoSQL approach, less suitable for structured queries

### 2. Database Schema: Single database with multiple tables

**Decision**: Use a single SQLite database file with tables for recordings, transcripts, logs, and state.

**Rationale**:
- Single file simplifies backup and portability
- Foreign key relationships between tables enable complex queries
- SQLite handles concurrent reads well, even with async writes

**Table Structure**:
- `recordings`: id, file_path, timestamp, duration, format
- `transcripts`: id, recording_id, text, language, model_used, timestamp
- `logs`: id, level, message, source, timestamp, metadata_json
- `state`: key, value_json, updated_at

### 3. Audio Storage: Date-based directory structure

**Decision**: Store audio files in `~/.local/share/whisper-dictate/recordings/YYYY/MM/DD/` directories.

**Rationale**:
- Date-based organization makes it easy to locate recordings
- Prevents directory from becoming too large with thousands of files
- Maintains file system performance

**Alternatives Considered**:
- Single directory with UUIDs - harder to navigate manually
- Hash-based subdirectories - unnecessary complexity

### 4. Migration Strategy: Versioned schema with automatic migration

**Decision**: Implement database schema versioning with automatic migrations on startup.

**Rationale**:
- Users don't need to manually run migrations
- Schema version tracking allows for future upgrades
- Fallback to recreate database if migration fails

### 5. Logging: Dual logging (file + database)

**Decision**: Continue file-based logging AND add database logging.

**Rationale**:
- File logs remain useful for debugging (tail -f)
- Database logs enable structured queries (filter by level, date, source)
- Low overhead: async writes don't impact performance

## Risks / Trade-offs

### Risk: Database file corruption
**Mitigation**:
- Implement periodic VACUUM to prevent corruption
- Keep WAL mode for better crash recovery
- Add database integrity check on startup

### Risk: Disk space exhaustion
**Mitigation**:
- Consider adding cleanup/retenance policy for old recordings
- Warn users when disk space is low
- Default to not saving recordings if space is limited

### Risk: Migration from existing state files
**Mitigation**:
- Detect existing state files on first run
- Migrate config and state to database
- Keep backup of original files until migration verified

### Risk: Performance impact from database writes
**Mitigation**:
- Use async writes throughout
- Batch inserts where possible
- Index only frequently queried columns
