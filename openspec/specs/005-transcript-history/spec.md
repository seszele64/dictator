# Transcript History Specification

## Purpose

This specification defines the transcript history capability of the whisper-dictate system: saving transcripts (with recording IDs) during the dictation workflow, listing/viewing/searching and deleting transcripts via the CLI, and ensuring history CLI commands exit cleanly. It also documents the database lifecycle pattern that all database-using CLI commands must follow.

## Requirements

### Requirement: Save transcripts during dictation workflow
The system SHALL automatically save transcripts to the database during the dictation workflow.

#### Scenario: Save transcript after successful transcription
- **GIVEN** a recording has been created in the database with a valid recording_id
- **WHEN** the transcription completes successfully
- **THEN** the transcript SHALL be saved to the database linked to the recording_id

#### Scenario: Preserve recording ID during transcription
- **GIVEN** a dictation session is in progress with a recording_id
- **WHEN** the recording stops and transcription begins
- **THEN** the recording_id SHALL remain available until after the transcript is saved

---

### Requirement: View transcription history
The system SHALL provide a command to view past transcriptions.

#### Scenario: List recent transcriptions
- **WHEN** the user runs the `history` command without options
- **THEN** the system displays a list of recent transcriptions with date, time, and preview of text (first 50 characters)

#### Scenario: Limit history results
- **WHEN** the user runs `history --limit N`
- **THEN** the system displays only the N most recent transcriptions

#### Scenario: Filter history by date
- **WHEN** the user runs `history --date YYYY-MM-DD`
- **THEN** the system displays only transcriptions from that specific date

---

### Requirement: View full transcript details
The system SHALL provide detailed view of individual transcripts.

#### Scenario: View transcript by ID
- **WHEN** the user runs `history show <id>`
- **THEN** the system displays the full transcript text, audio file path, duration, language, and timestamp

#### Scenario: View transcript with audio file
- **WHEN** the user runs `history show <id> --audio`
- **THEN** the system displays the transcript details along with the path to the saved audio file

---

### Requirement: Search transcripts
The system SHALL provide search functionality for transcripts.

#### Scenario: Search transcripts by text content
- **WHEN** the user runs `history search <query>`
- **THEN** the system searches transcript text and displays matching transcriptions with the query highlighted

#### Scenario: Case-insensitive search
- **WHEN** the user searches for a term
- **THEN** the search is case-insensitive and matches partial words

---

### Requirement: Delete transcript from history
The system SHALL allow deletion of transcripts from history.

#### Scenario: Delete single transcript
- **WHEN** the user runs `history delete <id>`
- **THEN** the system removes the transcript from the database and deletes the associated audio file

#### Scenario: Confirm deletion
- **WHEN** the user attempts to delete a transcript
- **THEN** the system prompts for confirmation before deletion

---

### Requirement: CLI commands exit cleanly
The system SHALL ensure all history CLI commands exit cleanly without hanging.

#### Scenario: History list command exits
- **WHEN** the user runs `history list` command
- **THEN** the command completes and exits without requiring Ctrl+C

#### Scenario: History show command exits
- **WHEN** the user runs `history show <id>` command
- **THEN** the command completes and exits without requiring Ctrl+C

#### Scenario: History search command exits
- **WHEN** the user runs `history search <query>` command
- **THEN** the command completes and exits without requiring Ctrl+C

#### Scenario: History delete command exits
- **WHEN** the user runs `history delete <id>` command
- **THEN** the command completes and exits without requiring Ctrl+C

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
