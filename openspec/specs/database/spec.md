# database Specification

## Purpose
TBD - created by archiving change fix-storage-safety. Update Purpose after archive.

## Requirements

### Requirement: Legacy databases complete all pending schema migrations
The system **SHALL** detect a legacy database — one where the core tables exist but no `schema_versions` row is recorded — and migrate it as if it were at baseline schema version 1, applying every pending migration up to `CURRENT_SCHEMA_VERSION`, and **MUST NOT** skip migrations by jumping from an unversioned state straight to `CURRENT_SCHEMA_VERSION` when tables already exist.

#### Scenario: Legacy database gains the updated_at column
- Given: a database file created with the old schema (recordings and transcripts tables exist, contain rows, and there is no `schema_versions` table)
- When: the application opens the database and migration runs
- Then: the database is treated as baseline version 1, the pending migration adds `updated_at` to the transcripts table, schema version 2 is recorded, and `update_transcript` succeeds instead of failing with `no such column: updated_at`

#### Scenario: Fresh database initializes at the current version
- Given: a brand-new database file with no tables
- When: the application initializes the database
- Then: the schema is created at `CURRENT_SCHEMA_VERSION` in one pass with no partial migration

#### Scenario: Already-current database is left untouched
- Given: a database already recorded at schema version 2
- When: the application opens the database and migration runs
- Then: no migration DDL executes and all existing data remains intact

---

### Requirement: Recording metadata queries match the recordings schema
The system **SHALL** select only columns that exist in the recordings table for recording metadata queries (`get_recording`, `list_recordings`), and **MUST NOT** select `updated_at` from the recordings table, which has no such column, while transcript queries continue to include `updated_at` because the transcripts table defines it.

#### Scenario: Listing recordings succeeds without column errors
- Given: a database whose recordings table has no `updated_at` column
- When: `list_recordings` or `get_recording` is called
- Then: the query succeeds without `OperationalError` and returns only recording rows

#### Scenario: Recording dicts contain only real columns
- Given: a recording row in the database
- When: its dict is returned by a metadata query
- Then: the dict contains no `updated_at` key, and transcript dicts still contain `updated_at`

---

### Requirement: Row-to-dict mapping fails loudly on schema drift
The system **SHALL** map database rows to dicts with strict column alignment so that a query selecting columns the table lacks (or a row with unexpected columns) raises an error instead of silently dropping values.

#### Scenario: Drifted query surfaces an error
- Given: a query that selects a column the target table does not have
- When: the row is mapped to a dict
- Then: an exception is raised during mapping rather than the phantom column being silently dropped

#### Scenario: Aligned queries map normally
- Given: a query whose selected columns all exist in the target table
- When: the row is mapped to a dict
- Then: every column value appears in the dict with no exception

---

### Requirement: Regression tests cover migration and schema alignment
The system **SHALL** include automated regression tests using a hand-built legacy-database fixture covering the migration backfill, the recordings query columns, and the strict row-mapping failure mode.

#### Scenario: Database regression test suite runs
- Given: a test suite with a legacy-schema fixture (old tables, no `schema_versions`), current-schema fixtures, and a drifted-query case
- When: the test suite is executed
- Then: the legacy fixture migrates to version 2 with `updated_at` present, recordings queries return full dicts without phantom columns, and the drifted query raises during mapping

### Requirement: Processed output is stored alongside immutable raw transcript text

The transcripts schema **SHALL** gain nullable `processed_text`, `processed_prompt`, `processed_model`, and `processed_at` columns, and processing **MUST NOT** modify the original `text` or `updated_at` values of a transcript row.

#### Scenario: Raw text survives processing

- **GIVEN** a transcript with raw text "um so hello there"
- **WHEN** processing stores "Hello there."
- **THEN** the row's `text` remains "um so hello there"
- **AND** `processed_text` is "Hello there.", with the prompt and effective model stored in the metadata columns

#### Scenario: Unprocessed transcripts remain distinguishable

- **GIVEN** a transcript that has never been processed
- **WHEN** the row is read
- **THEN** `processed_text`, `processed_prompt`, `processed_model`, and `processed_at` are all null

#### Scenario: Transcript text edits do not inherit processed output

- **GIVEN** a transcript with stored processed output
- **WHEN** the user edits the raw transcript through the existing history update command
- **THEN** the raw `text` changes, `updated_at` changes as before, and the `processed_*` columns are left as they were

#### Scenario: Stale processed output is retained, not cleared

- **GIVEN** a transcript with `processed_text` "Old result" and `processed_at` "2026-11-07 10:00:00"
- **WHEN** `update_transcript()` replaces the raw text at "2026-11-07 11:00:00"
- **THEN** all four `processed_*` columns keep their previous values and `processed_at` is not refreshed
- **AND** `updated_at` is now later than `processed_at`, which is the documented staleness signal used by `history show`
- **AND** clearing the processed fields on edit is explicitly rejected because it would destroy the only record of the previous result

#### Scenario: Reproducing after an edit refreshes the staleness signal

- **GIVEN** a stale processed row whose `updated_at` is later than `processed_at`
- **WHEN** the user runs processing again and the result is stored
- **THEN** `processed_at` is newer than `updated_at` and the row is no longer stale

---

### Requirement: Schema version 3 migration is additive and idempotent

The system **SHALL** migrate databases to schema version 3 by adding only the processed-output columns that are absent, and re-running initialization on an already-current database **MUST NOT** execute duplicate column additions or fail.

#### Scenario: Version 2 database upgrades

- **GIVEN** a database recorded at schema version 2 with existing transcripts
- **WHEN** the application initializes the database
- **THEN** the four processed-output columns are added, existing rows are preserved with null processed values, and schema version 3 is recorded

#### Scenario: Fresh database starts at version 3

- **GIVEN** a new database file with no tables
- **WHEN** the application initializes the database
- **THEN** the transcripts table is created with the processed-output columns in one pass and schema version 3 is recorded

#### Scenario: Legacy database migrates through version 2 to version 3

- **GIVEN** a legacy database whose tables exist but no schema version is recorded
- **WHEN** the application initializes the database
- **THEN** it is treated as baseline version 1, migration 2 adds `updated_at`, migration 3 adds the processed-output columns, and version 3 is recorded

#### Scenario: Already-current database is untouched

- **GIVEN** a database recorded at schema version 3
- **WHEN** the application initializes the database again
- **THEN** no column DDL runs and all stored processed values remain intact

---

### Requirement: The newest non-empty transcript is selectable in one query

The database layer **SHALL** expose a query returning the newest transcript whose trimmed `text` is non-empty, ordered by timestamp descending then id descending, and **MUST** return no row when every transcript is empty. Trimming **SHALL** use the exact set `space`, `\t`, `\n`, `\r`, `\f`, `\v` (SQL `TRIM(text, ' ' || char(9) || char(10) || char(13) || char(12) || char(11))`), and the Python check **MUST** use `.strip(" \t\n\r\f\v")` so both layers agree.

#### Scenario: Empty rows are filtered out

- **GIVEN** transcripts with ids 1 (non-empty), 2 (empty), and 3 (empty)
- **WHEN** the newest processable transcript is queried
- **THEN** the row with id 1 is returned

#### Scenario: Whitespace-only rows of every kind are filtered out

- **GIVEN** transcripts whose text is `" "`, `"\t"`, `"\n\r"`, `"\f"`, or `"\v"` and one older transcript with real text
- **WHEN** the newest processable transcript is queried
- **THEN** every whitespace-only row is skipped and the older real transcript is returned

#### Scenario: Ordering is timestamp then id

- **GIVEN** non-empty transcripts with timestamps 10:00 (id 5) and 10:00 (id 7), plus 11:00 (id 4)
- **WHEN** the newest processable transcript is queried
- **THEN** the timestamp 11:00 row is returned first, and ties at 10:00 would resolve to id 7

#### Scenario: No processable transcript

- **GIVEN** the transcript table is empty or all rows have empty text
- **WHEN** the newest processable transcript is queried
- **THEN** the query returns no row

---

### Requirement: Every transcript reader exposes the processed columns after migration

Because `_row_to_dict` zips rows against an explicit column list with `strict=True`, adding columns to `transcripts` **SHALL** be accompanied in the same change by updating every `SELECT *`-based reader (`get_transcript`, `get_transcript_by_recording`, `list_transcriptions`, `get_transcription_with_recording`) to include the four `processed_*` columns. A shorter column list **MUST** be treated as a defect, because the reader would raise instead of returning data.

#### Scenario: All transcript readers return the processed keys

- **GIVEN** a version 3 database containing a processed transcript
- **WHEN** `get_transcript`, `get_transcript_by_recording`, `list_transcriptions`, and `get_transcription_with_recording` are called
- **THEN** each returned dict contains `processed_text`, `processed_prompt`, `processed_model`, and `processed_at`
- **AND** no `ValueError` from a length-mismatched `zip` is raised

#### Scenario: Migration and reader updates land atomically

- **GIVEN** the change is reviewed as a whole
- **WHEN** migration 3 exists without the reader column lists updated
- **THEN** the change is rejected, because reading any transcript on a migrated database would fail

---

### Requirement: Successful reprocessing overwrites processed fields atomically

Storing a processing result **SHALL** update `processed_text`, `processed_prompt`, `processed_model`, and `processed_at` for the selected transcript in a single update, replacing any previous processed values.

#### Scenario: First processing writes all metadata

- **GIVEN** a transcript with no processed values
- **WHEN** a result is stored for prompt "Summarize" and model "gpt-4o-mini"
- **THEN** all four processed columns are populated and `processed_at` records the current time

#### Scenario: Second processing replaces the first

- **GIVEN** a transcript whose processed text is "First result" from prompt A
- **WHEN** a result is stored for prompt B
- **THEN** `processed_text` holds the new result, `processed_prompt` holds prompt B, and no trace of prompt A remains in the processed columns

#### Scenario: Failure performs no partial write

- **GIVEN** a transcript with an existing processed result
- **WHEN** storing a new result fails before the update
- **THEN** the row retains all previous processed values unchanged

#### Scenario: Unknown transcript id is reported

- **GIVEN** no transcript row has the requested id
- **WHEN** a result is stored for that id
- **THEN** the store operation reports that no row was updated instead of creating a new transcript

#### Scenario: Stored model is exactly the value passed by the caller

- **GIVEN** a result stored with model `gpt-4o-mini`
- **WHEN** the row is read
- **THEN** `processed_model` is `gpt-4o-mini`
- **AND** the caller is responsible for passing the stripped effective model, so the store never re-derives or defaults it
