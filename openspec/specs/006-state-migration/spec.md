# State Migration Specification

## Purpose

This specification defines the state migration capability of the whisper-dictate system: detecting legacy state files on startup, migrating configuration from JSON into the database, migrating application state (including notification state), and handling migration failures gracefully (rollback, retry, and skip-if-already-migrated).

## Requirements

### Requirement: Detect existing state files
The system SHALL detect existing state files from previous versions.

#### Scenario: Check for legacy state files on startup
- **WHEN** the application starts for the first time after this update
- **THEN** the system checks for legacy state files in the config directory

#### Scenario: Identify state file locations
- **WHEN** legacy state files are present
- **THEN** the system identifies which files contain config, state, and historical data

---

### Requirement: Migrate configuration to database
The system SHALL migrate existing configuration to the database.

#### Scenario: Migrate config from JSON
- **WHEN** legacy config file exists
- **THEN** the system reads the config values and stores them in the database's state table

#### Scenario: Backup original config
- **WHEN** config migration begins
- **THEN** the system creates a backup of the original config file before migration

#### Scenario: Verify migration success
- **WHEN** config is migrated
- **THEN** the system verifies the migrated values match the original and logs success or failure

---

### Requirement: Migrate application state
The system SHALL migrate application state from files to database.

#### Scenario: Migrate notification state
- **WHEN** notification state file exists
- **THEN** the system migrates notification IDs and timestamps to the database

#### Scenario: Mark state as migrated
- **WHEN** all state files are successfully migrated
- **THEN** the system records migration status to prevent re-running migrations

---

### Requirement: Handle migration failures gracefully
The system SHALL handle migration failures without breaking the application.

#### Scenario: Rollback on migration failure
- **WHEN** migration encounters an error
- **THEN** the system rolls back partial changes, logs the error, and continues with default values

#### Scenario: Manual migration retry
- **WHEN** automatic migration fails
- **THEN** the system provides a `migrate` command to retry migration manually

#### Scenario: Skip migration if already done
- **WHEN** migration has already been completed
- **THEN** the system skips migration and uses the database directly

---

## CLI Integration

### Database Lifecycle Requirements

All CLI commands that interact with the database MUST follow the database lifecycle pattern:

#### Required Pattern

1. **Initialization**: Call `asyncio.run(db.initialize())` before any database operations
2. **Cleanup**: Call `asyncio.run(db.close())` in a `finally` block after operations complete

#### Implementation Options (in priority order)

1. **Preferred**: Use the `@with_database` decorator from `whisper_dictate.cli_helpers`
2. **Alternative**: Manual try/finally pattern (if decorator insufficient)

#### Example

```python
@cli.command()
@with_database
@click.pass_context
def command_name(ctx, ...):
    db = ctx.obj['db']
    results = asyncio.run(db.some_query())
```

#### Verification

- All database-using CLI commands must include `db.close()` in their execution path
- Commands should not hang on exit after completion
- Commands must call `initialize()` before querying
