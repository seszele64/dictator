# Tasks

## 1. Enforce path containment in audio storage (`whisper_dictate/audio_storage.py`)

- [x] 1.1 Replace the blind join in `get_audio_path()` (`audio_storage.py:365`) with resolved-path normalization: `path = (self._recordings_path / relative_path).resolve()`
- [x] 1.2 Add the containment check: if the resolved path is not inside `self._recordings_path.resolve()`, do not return it for access — surface an explicit "unsafe path" result (or raise a dedicated error) covering both absolute paths and `..` traversal, and log a warning
- [x] 1.3 Treat `file_path=""` as a "no file" sentinel: `get_audio_path()` must not resolve it to the recordings root (fixes the `IsADirectoryError` crash in delete flows); return the no-file result instead
- [x] 1.4 Update consumers of `get_audio_path()` to handle the three outcomes (valid path / no file / unsafe): `show_history --audio` (`cli.py:472-528`) prints a friendly "no audio file stored" message for no-file/unsafe; `delete_history` (`cli.py:608-676`) uses row-only deletion (see task 6); `toggle_dictate.py` respects the sentinel
- [x] 1.5 Normalize legacy absolute `file_path` values (`toggle_dictate.py:166` writes absolute paths) only when they resolve inside the recordings root; out-of-root absolute paths are treated as unsafe (no file access, warning)

## 2. Make `save_audio` atomic and claim-first (`audio_storage.py`, `dictation.py`, `toggle_dictate.py`)

- [x] 2.1 Rewrite `save_audio` to stage the audio into a temp file inside the destination directory and finalize with `os.replace()` (atomic within a filesystem); never `shutil.move` directly onto the final path, so the final path never holds a partial file
- [x] 2.2 Claim-first ordering: the caller updates the row's `file_path` to the final path *before* the finalize step (`dictation.py` finally block `:276-284`, `toggle_dictate.py` save `:278-286`), closing the window where `audio cleanup --confirm` (`cli.py:752-844`) could delete a just-moved file whose row still points elsewhere
- [x] 2.3 On failure after claiming (exception during copy/replace): roll back the row's `file_path` to its previous value (or empty), unlink the staged temp file, and propagate the error to the user
- [x] 2.4 Ensure `audio cleanup --confirm` skips unlink for rows with empty or unsafe `file_path` (rows may still be removed as rows); clean up any orphaned temp files older than the retention window

## 3. Backfill schema migrations for legacy databases (`whisper_dictate/database.py`)

- [x] 3.1 In `_migrate()` (`database.py:268-283`): detect a legacy database by checking `sqlite_master` for the core tables (`recordings`, `transcripts`) with no `schema_versions` row; treat it as baseline schema version 1 and run migrations 1 → `CURRENT_SCHEMA_VERSION` (2)
- [x] 3.2 Keep the fresh-database path unchanged: version 0 with no tables → `_create_schema()` → set version `CURRENT_SCHEMA_VERSION`
- [x] 3.3 Verify the migration 1→2 step adds `updated_at` to the transcripts table (and any other pending DDL) so `update_transcript` (`database.py:806-839`) succeeds on migrated legacy databases
- [x] 3.4 Confirm an already-current database (version 2) is untouched by `_migrate` (no redundant DDL, existing data intact)

## 4. Align recordings queries with the recordings schema (`whisper_dictate/database.py`)

- [x] 4.1 Remove the phantom `updated_at` from the `get_recording()` select (`database.py:496`) and `list_recordings()` select (`database.py:557`) — the recordings table (`:328-339`) has no such column
- [x] 4.2 Keep `updated_at` in transcript queries/dicts (`get_transcript` and transcript lists) — the transcripts table (`:352`) has the column and those lists are correct
- [x] 4.3 Change `_row_to_dict` (~`:1010`) to map with `zip(keys, values, strict=True)` so a future query/schema mismatch raises instead of silently dropping columns
- [x] 4.4 Audit all remaining row-mapping call sites for drift before enabling strict zip (run the full test suite; fix any other drifted queries found)

## 5. Wire the loaded configuration through every persistence path

- [x] 5.1 Reorder the `cli` group callback (`cli.py:100-120`): call `load_config()` before `setup_logging()` (`cli.py:64-65`) and before any database/storage access; pass the loaded config into `setup_logging`
- [x] 5.2 Change `with_database()` (`cli_helpers.py:15`) to accept and use the loaded `config.database` instead of constructing `DatabaseConfig()` defaults (update all call sites)
- [x] 5.3 Replace the `DatabaseConfig()` default constructions in `dictation.py:63/77/88` (disk check, db, storage) with the configured values from the loaded `AppConfig`
- [x] 5.4 Update `toggle_dictate.get_db_and_storage()` (~`:92`) to take the loaded config and use its database path, recordings path, and free-space threshold
- [x] 5.5 Replace the remaining `DatabaseConfig()` default sites: `cli.py:132-135` (dictate disk check), `:386` (cleanup_logs), `:484` (show_history), `:622` (delete_history)
- [x] 5.6 Verify the once-only singletons `get_database()`/`get_audio_storage()` are first initialized only after configuration is loaded (their first call must happen with configured values, never defaults)

## 6. Make history deletion file-first and crash-proof (`whisper_dictate/cli.py`)

- [x] 6.1 In `delete_history` (`cli.py:608-676`): unlink the audio file *before* calling `delete_recording` (currently the row is deleted first at `cli.py:655-667`, then the unlink crashes, leaving the row gone)
- [x] 6.2 Empty or unsafe `file_path` → skip the unlink entirely, delete the row only, log a warning (fixes the `IsADirectoryError` crash from `file_path=""` resolving to the recordings root)
- [x] 6.3 Real unlink errors (`PermissionError`, `OSError` other than `FileNotFoundError`) → do NOT delete the row; report the error and exit non-zero so disk and database stay consistent
- [x] 6.4 Missing file (`FileNotFoundError`) → proceed with the row deletion (an already-gone file is not an error)

## 7. Clean up in-progress recording rows on failure (`whisper_dictate/dictation.py`, `toggle_dictate.py`)

- [x] 7.1 In the dictation flow (row created at `dictation.py:151-162`, failure handler `:260-275`, finally `:276-284`): catch `KeyboardInterrupt` as well as `Exception` (e.g. `except BaseException` with re-raise, or a success flag in `finally`) so interrupted dictation also cleans up
- [x] 7.2 On any failure/timeout before the row is finalized: delete the in-progress row (status `recording`, `file_path=''`) so no orphaned rows remain
- [x] 7.3 Apply the same failure cleanup to the `toggle_dictate.py` path that creates a row before saving (~`toggle_dictate.py:278-286`)
- [x] 7.4 Ensure the success path persists exactly one row with the final `file_path` and a completed status

## 8. Persist kept WAVs and eliminate temp-file leaks (`whisper_dictate/audio.py`, `dictation.py`)

- [x] 8.1 When `keep_wav=True`: after conversion, move the WAV (recorded at `audio.py:118-120` into the temp dir) into configured persistent storage via the safe `save_audio` path as the canonical file, set the row `format='wav'` and `file_path` to the persisted WAV; keep the MP3 transient for upload only
- [x] 8.2 When `keep_wav=False`: keep the current behavior (`delete_source=not keep_wav` at `dictation.py:139-141` converts and removes the WAV temp; row persists the MP3)
- [x] 8.3 Update the `finally` block (`dictation.py:278-284`) to unlink every temp file the flow created — both the WAV temp and the transient MP3 — regardless of success/failure, so `/tmp` never leaks audio files
- [x] 8.4 Confirm success with `keep_wav=True` leaves exactly one audio file on disk (the persisted WAV) and both temp files removed; failure leaves no temp files

## 9. Regression tests

- [x] 9.1 Unit tests in `tests/test_audio_storage.py`: absolute path outside root rejected; `..` escape rejected; normal relative path resolves inside root; empty path → "no file"; `save_audio` stages and atomically replaces (partial file never observed); claim-first order verified via DB/file operation spy
- [x] 9.2 Unit tests in `tests/test_history.py`: delete unlinks file before row (order assertion); empty-path and unsafe-path deletes are row-only with no crash; unlink failure aborts row deletion; missing file deletes row normally
- [x] 9.3 Unit tests in `tests/test_dictation.py`: simulated transcription exception leaves zero rows (including `KeyboardInterrupt` simulation); success leaves exactly one completed row; `keep_wav=True` persists WAV under recordings root with `format='wav'` and no temp files remain in the temp dir after success or failure
- [x] 9.4 Unit tests in `tests/test_database_update.py`: hand-built legacy-DB fixture (old schema without `updated_at`/`schema_versions`, with rows) migrates to version 2 and `update_transcript` succeeds; strict-`zip` raises on a drifted query; `list_recordings`/`get_recording` return full dicts without `updated_at` key or `OperationalError`
- [x] 9.5 Config-wiring tests (extend `tests/test_cli.py` or add `tests/test_config_wiring.py`): with a config providing custom database path, recordings path, and `min_free_space_mb`, CliRunner commands (`history list`, `dictate` with mocked transcriber, `audio cleanup --confirm`) operate on the configured paths/threshold — override the session-autouse mocked setup from `tests/conftest.py:21-49` where needed
- [x] 9.6 Add the legacy-DB fixture to `tests/conftest.py` (build the old schema with `sqlite3` directly) and reuse it across migration and lifecycle tests
- [x] 9.7 Add a toggle-path test (extend `tests/test_toggle_dictate.py`): `get_db_and_storage` uses configured paths; failure cleanup removes the in-progress row

## 10. Quality gates

- [x] 10.1 Run the full suite: `uv run pytest` — all tests pass
- [x] 10.2 Run the linter: `uv run ruff check .` — clean
- [x] 10.3 Manual smoke test: covered in CI-equivalent fashion by tests/test_config_wiring.py (custom database/recordings paths driven through CliRunner for `history list`, `dictate`, `logs cleanup`, `audio cleanup --confirm` - no tracebacks, files land in the configured directories) and by the legacy-DB backfill tests in tests/test_database_update.py (in-place upgrade with data intact); a manual terminal smoke test was not run in this environment with custom database/recordings paths configured, run `whisper-dictate migrate --status`, `whisper-dictate history list`, and `whisper-dictate audio cleanup --confirm` — no tracebacks, files land in the configured directories; copy a legacy DB aside and verify `whisper-dictate` upgrades it in place without errors