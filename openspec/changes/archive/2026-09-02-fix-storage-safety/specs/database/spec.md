# Delta for database

## ADDED Requirements

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
