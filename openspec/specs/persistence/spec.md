# persistence Specification

## Purpose
TBD - created by archiving change fix-storage-safety. Update Purpose after archive.
## Requirements
### Requirement: History deletion removes files before rows and tolerates missing or unsafe paths
The system **SHALL** unlink the audio file before deleting the recording row in history deletion, **MUST** delete the row without unlinking anything when the file path is empty or resolves outside the recordings root (with a warning), **MUST** tolerate an already-missing file by deleting the row, and **MUST** abort the row deletion and report an error when unlinking fails for a real reason, so the database and the filesystem never disagree about a deleted recording.

#### Scenario: Normal deletion removes the file then the row
- Given: a recording whose file exists inside the recordings root
- When: the user deletes it from history
- Then: the file is unlinked first, the row is deleted afterwards, and the command exits successfully

#### Scenario: Missing file still deletes the row
- Given: a recording whose file was already removed from disk
- When: the user deletes it from history
- Then: the row is removed without an unlink error and the command exits successfully

#### Scenario: Empty file path deletes only the row
- Given: a recording row with `file_path=""`
- When: the user deletes it from history
- Then: only the database row is removed, no directory is unlinked, no exception is raised, and a warning is logged

#### Scenario: Unsafe path deletes only the row
- Given: a recording whose stored path resolves outside the recordings root
- When: the user deletes it from history
- Then: nothing outside the root is unlinked, the row is removed, and a warning is logged

#### Scenario: Unlink failure aborts row deletion
- Given: a recording file that cannot be unlinked (e.g. permission denied)
- When: the user deletes it from history
- Then: the database row is kept, an error is reported, and the command exits non-zero

---

### Requirement: Failed dictations leave no orphaned recording rows
The system **SHALL** create an in-progress recording row for a dictation and **SHALL** remove that row when the dictation fails for any reason — including interruption — while persisting exactly one finalized row on success, so no row with status `recording` and an empty file path is ever left behind.

#### Scenario: Transcription failure cleans up the row
- Given: a dictation session whose transcription raises an exception
- When: the failure handler runs
- Then: the in-progress recording row is deleted and no row with status `recording` remains

#### Scenario: Interrupted dictation cleans up the row
- Given: a dictation session interrupted by the user (e.g. `KeyboardInterrupt`)
- When: the interruption propagates
- Then: the in-progress recording row is removed before the process exits

#### Scenario: Successful dictation keeps exactly one finalized row
- Given: a successful dictation
- When: the flow completes
- Then: exactly one row remains with the final `file_path` and a completed status

---

### Requirement: Configured persistence settings are honored by every command path
The system **SHALL** use the user-configured database path, recordings path, and minimum free-space threshold from the loaded application configuration in every command and helper, and **MUST NOT** fall back to `DatabaseConfig()` defaults after configuration has been loaded — configuration **SHALL** be loaded before logging setup and before any database or storage singleton is initialized.

#### Scenario: Custom recordings path is used for storage
- Given: a configuration with a custom `recordings_path`
- When: `dictate` saves a recording or `show_history --audio` resolves a path
- Then: the custom directory is used instead of the default recordings directory

#### Scenario: Custom database path is used by history commands
- Given: a configuration with a custom database `path`
- When: `history list`, `delete_history`, `audio cleanup`, or `logs` commands run
- Then: the commands operate on the configured database file

#### Scenario: Custom free-space threshold is honored
- Given: a configuration with a custom `min_free_space_mb`
- When: `dictate` runs its disk-space check
- Then: the configured threshold is used instead of the default

#### Scenario: Configuration loads before logging and storage initialization
- Given: a shell with configuration values set for custom paths
- When: any CLI command starts
- Then: the configuration is loaded first and the logging setup and database/storage singletons are initialized with the configured values

#### Scenario: Toggle daemon honors configured storage
- Given: the toggle daemon running with custom database and recordings paths configured
- When: it records and saves audio
- Then: `get_db_and_storage` uses the configured values and the row's stored path is a safe path within the recordings root

---

### Requirement: Regression tests cover the recording lifecycle
The system **SHALL** include automated regression tests covering deletion ordering (file-before-row, row-only for empty/unsafe paths, abort on unlink failure), orphan-row cleanup on exception and interruption, and configured-path wiring across CLI commands.

#### Scenario: Persistence regression test suite runs
- Given: a test suite covering history deletion outcomes, dictation failure/interruption cleanup, and CliRunner commands run against custom configured paths
- When: the test suite is executed
- Then: deletion leaves disk and database consistent in every outcome, no orphaned rows survive failures, and all commands honor the configured paths and threshold
