# Design: Fix storage and persistence safety

## Technical Approach

Eight verified defects are fixed in four layers, each with dedicated regression tests:

1. **Path safety** (`whisper_dictate/audio_storage.py:365`): `get_audio_path()` currently does `self._recordings_path / relative_path` with no normalization or containment check — an absolute `file_path` replaces the base entirely, and `..` escapes it (absolute paths are actually written by `toggle_dictate.py:166`). Fix: resolve the joined path, verify the result is inside the resolved recordings root, and reject everything else. `file_path=""` (silence rows from `dictation.py:174-182`) becomes an explicit "no file" sentinel instead of resolving to the recordings root (which causes the `IsADirectoryError` crash in `delete_history`). Legacy absolute paths are accepted only when they resolve inside the root; otherwise the recording is treated as fileless with a warning, and files outside the root are never read or unlinked.
2. **Atomic, claim-first saves** (`save_audio` in `audio_storage.py`, callers in `dictation.py`/`toggle_dictate.py:278-286`): stage the audio as a temp file inside the destination directory, then `os.replace()` into the final path (atomic within a filesystem; a copy covers cross-device moves). The caller updates the row's `file_path` before finalizing and rolls back on failure, so `audio cleanup --confirm` can never delete a just-moved file whose row still points elsewhere, and the final path never contains a partial file.
3. **Database layer** (`database.py`): `_migrate` (`:268-283`) currently treats "version 0" as fresh, calling `_create_schema()` (a no-op on existing tables via `CREATE TABLE IF NOT EXISTS`) and jumping to version 2 — so legacy databases never get `updated_at` and `update_transcript` (`:806-839`) fails forever. Fix: when core tables exist but no `schema_versions` row is present (detected via `sqlite_master`), treat the database as baseline version 1 and run migrations 1→CURRENT. Fresh databases keep the version 0 → create → CURRENT path. `get_recording`/`list_recordings` (`:496`, `:557`) drop the phantom `updated_at` select (recordings schema `:328-339` has no such column; `CURRENT_SCHEMA_VERSION` stays 2). `_row_to_dict` (~`:1010`) switches to `zip(..., strict=True)` so any future query/schema mismatch raises instead of silently dropping values.
4. **Config wiring and lifecycle** (`cli.py`, `cli_helpers.py`, `dictation.py`, `toggle_dictate.py`): the `cli` group callback loads configuration *before* `setup_logging` and before any songleton database/storage initialization; `with_database` and toggle `get_db_and_storage()` receive the loaded `config.database`; the remaining `DatabaseConfig()` default sites are replaced. `delete_history` becomes file-first with per-outcome handling (row-only for empty/unsafe/missing paths, abort row deletion on real unlink errors). The dictation flow (row created at `dictation.py:151-162`, failure handler `:260-275`, finally `:276-284`) removes the in-progress row on any failure including `KeyboardInterrupt`. `keep_wav=True` persists the WAV into configured storage as the canonical file (row `format='wav'`), with the MP3 transient for upload only; both temp files are unlinked in `finally` — no `/tmp` leak.

## Architecture Decisions

### Decision: Treat empty `file_path=""` as a "no file" sentinel rather than resolving to the recordings root
- Pros: Eliminates the `IsADirectoryError` crash class in `delete_history`; semantically honest (row exists, no file on disk); trivially testable
- Cons: Consumers must handle the sentinel explicitly — `show_history --audio` must print a friendly "no audio file" message instead of constructing a path

### Decision: Resolve-and-containment-check every stored path; never access files outside the recordings root
- Pros: Closes the path-escape (absolute replacement, `..` traversal) at the single chokepoint `get_audio_path()`; legacy absolute paths that genuinely point inside the root (e.g. from `toggle_dictate.py:166`) keep working, so no existing data becomes inaccessible
- Cons: Recordings stored outside the root by power users silently lose file access (playback says "no audio", delete becomes row-only) — mitigated by a logged warning; no file is ever deleted

### Decision: History deletion is file-first with per-outcome handling
- Pros: The database row is never deleted before its file, so a crash or error cannot leave a row-less file or a row pointing at a deleted file; empty/unsafe/missing paths degrade gracefully (row-only delete + warning) instead of crashing
- Cons: Behavior change — an unlinkable file (e.g. permission error) now aborts row deletion and exits non-zero rather than "succeeding" after deleting the row first

### Decision: Migration backfill treats "core tables exist, no schema_versions row" as baseline schema version 1
- Pros: Legacy databases get `updated_at` and `update_transcript` works again without data loss; reuses the existing migration 1→2 code path instead of duplicating DDL
- Cons: Assumes pre-versioning databases were at schema v1 (verified: the old schema is exactly v1); a database with unrelated tables would be misdetected — acceptable for this application's single known schema history

### Decision: Do not add migration 3; remove the phantom `updated_at` from recordings queries instead
- Pros: `CURRENT_SCHEMA_VERSION` stays 2, no rewrite risk for live recordings tables; transcripts keep their real `updated_at` column (schema `:352`)
- Cons: None meaningful — the queries were simply wrong; no schema change is required

### Decision: `_row_to_dict` maps rows with `zip(..., strict=True)`
- Pros: Future query/schema drift becomes a loud, test-failing error instead of silently dropping columns from dicts
- Cons: Any currently-drifted query surfaces as an error at runtime — which is the intent; the known drift (recordings `updated_at`) is fixed in the same change

### Decision: Load configuration before logging setup and pass `config.database` everywhere; remove `DatabaseConfig()` default constructions
- Pros: The once-only `get_database`/`get_audio_storage` singletons initialize with user values, so custom paths and thresholds finally work; one source of truth for persistence settings
- Cons: Requires reordering the CLI callback (config load must not depend on logging); callers and tests that relied on defaults must be updated

### Decision: `keep_wav=True` persists the WAV to storage as the canonical file (`format='wav'`); the MP3 is transient for upload only
- Pros: Users keep a real WAV in persistent storage instead of losing it to `/tmp`; upload still uses the compact MP3; no temp-file leak once `finally` unlinks both files
- Cons: Doubles storage usage while `keep_wav` is on; row `format` semantics change ('wav' vs 'mp3') and must be reflected at row creation and in history display

### Decision: `save_audio` = stage-then-`os.replace()` plus claim-first `file_path` update with rollback
- Pros: The final path only ever appears with complete content (no partial files from interrupted cross-device moves); `audio cleanup` cannot delete a file whose row still references the pre-move location
- Cons: Two-phase complexity — update and move must be atomic-as-a-unit via rollback on failure; needs a real error path (e.g. `ENOSPC`) in integration tests

## Data Flow

```text
cli group callback:  load_config() ──► setup_logging(config) ──► with_database(config.database)
                                            │
        ┌───────────────────────────────────┴───────────────────────────────┐
        │                                                                   │
history delete ── resolve file_path (containment check)                      │
        ├─ empty/unsafe ── row-only delete + warning                         │
        ├─ missing file   ── row delete (FileNotFoundError is not an error)  │
        └─ file exists    ── unlink file ──► delete_recording(row)           │
                                            │                                │
dictate ── create row (status=recording) ── record ── convert/upload         │
        ├─ success ── save_audio (claim file_path → stage → os.replace)      │
        ├─ failure/KeyboardInterrupt ── delete in-progress row               │
        └─ keep_wav=True ── persist WAV as canonical (format='wav');          │
                           MP3 transient; finally unlinks both temp files    │
                                            │                                │
legacy DB open ── _migrate: tables exist, no schema_versions ──►             │
        baseline v1 ──► migration 2 ──► schema version 2 ── update_transcript┘
```

## File Changes

- `whisper_dictate/audio_storage.py` — `get_audio_path()`: resolve, normalize, containment check, empty-path sentinel, unsafe-path result type; `save_audio()`: stage-to-temp + `os.replace()`, no direct `shutil.move` to the final path; expose a `safe_path()`/containment helper for callers
- `whisper_dictate/database.py` — `_migrate()`: legacy-DB detection (tables present, no version row) → baseline v1 → run migrations to `CURRENT_SCHEMA_VERSION`; `get_recording()`/`list_recordings()`: drop phantom `updated_at`; `_row_to_dict()`: `zip(..., strict=True)`
- `whisper_dictate/cli.py` — group callback order: `load_config()` before `setup_logging()`; `dictate` disk check (`:132-135`), `show_history` (`:484`), `delete_history` (`:622`, `:608-676`: file-first with per-outcome handling), `cleanup_logs` (`:386`), `audio cleanup` (`:752-844`): use configured values and skip empty/unsafe paths; `show_history --audio` friendly "no audio" message
- `whisper_dictate/cli_helpers.py` — `with_database()` (`:15`): accept and use the loaded `config.database`
- `whisper_dictate/dictation.py` — use `config.database` (`:63/77/88`); row cleanup on all failures incl. `KeyboardInterrupt` (`:260-284`); `keep_wav` persistence with row `format='wav'`; unlink both temp files in `finally` (`:278-284`)
- `whisper_dictate/toggle_dictate.py` — `get_db_and_storage()` (~`:92`): take the loaded config; store safe relative paths (`:166`); save with claim-first ordering (`:278-286`); failure-path row cleanup
- `whisper_dictate/audio.py` — `record_to_file` (`:118-120`): remain /tmp-transient, but mark the WAV as moveable into storage when `keep_wav` is set
- `tests/test_audio_storage.py` — path containment (absolute/`..`/empty), atomic save, claim-first ordering
- `tests/test_history.py` — delete ordering, empty/unsafe-path row-only, unlink-failure abort
- `tests/test_dictation.py` — orphan-row cleanup on exception and `KeyboardInterrupt`, `keep_wav` persistence, no `/tmp` leak
- `tests/test_database_update.py` (+ legacy-DB fixture in `tests/conftest.py`) — legacy backfill to v2, strict-zip drift, recordings columns
- `tests/test_cli.py` (or extend existing) — configured paths honored end-to-end via CliRunner (override the session-autouse mocked setup in `tests/conftest.py:21-49` where needed)

## Risks / Mitigations

- **Risk**: Legacy absolute paths outside the recordings root lose playback/delete-file capability.
  **Mitigation**: Normalization-inside-root keeps valid in-root absolute paths working; out-of-root paths degrade to fileless rows with a warning; their files are never deleted.
- **Risk**: File-first deletion changes user-visible behavior (real unlink errors now fail the command instead of deleting the row).
  **Mitigation**: Missing files are explicitly not an error (row-only delete), so already-broken recordings still clean up; only genuine unlink failures abort.
- **Risk**: Migration backfill misdetects a database that has tables but is not the known legacy schema.
  **Mitigation**: Detection requires the specific core tables (`recordings`, `transcripts`) to exist and no `schema_versions` row; covered by a hand-built legacy fixture test.
- **Risk**: Strict `zip` in `_row_to_dict` could break queries that already drift beyond the known one.
  **Mitigation**: Audit all query/row mappings before flipping; the change ships the fix for the only known drift and the test suite covers every mapping used.
- **Risk**: Reordering the CLI callback (config before logging) could affect startup error reporting.
  **Mitigation**: `load_config` is pure (env/file reads) and does not need logging; errors in it already print before logging is set up, preserving current behavior.
- **Risk**: `keep_wav` doubles storage usage and changes row `format`.
  **Mitigation**: Feature is opt-in (`keep_wav` flag) and documented; history display shows the stored format after the change.
