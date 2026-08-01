# Tasks

## A. Tooling and Artifacts
- [x] Create OpenSpec change artifacts (proposal, specs, design, tasks)
- [x] Add pytest-cov to dev dependencies in pyproject.toml
- [x] Add coverage collection step to CI (no threshold yet)

## B. Test Infrastructure
- [x] Reorganize tests into unit/, integration/, contract/, e2e/ directories
- [x] Harden conftest.py with real_db, real_db_config, db_singleton_reset, env_isolator, tmp_recordings_dir fixtures
- [x] Deduplicate test_history.py and test_cli_database_lifecycle.py

## C. Database Integration Tests
- [x] Write DB schema/migration/init tests (fresh schema, v1→v2 migration, PRAGMAs, idempotent init, integrity)
- [x] Write DB CRUD tests (recordings, transcripts, logs, state — all filters, JOINs, JSON round-trip)
- [x] Write DB transactions + FK cascade tests (rollback, nested, FK enforcement, cascade delete)

## D. Database Maintenance and Concurrency
- [x] Write DB maintenance tests (cleanup_old_logs with real timestamps)
- [x] Write concurrency probe test (document thread-bound sqlite3.Connection behavior)
- [x] Apply minimal testability fix if concurrency defect confirmed (requires explicit approval)

## E. Module-Specific Tests
- [x] Write config.py tests (load_config, provider enum, API key fallback, XDG paths, validation errors)
- [x] Write provider contract tests (ABC conformance, TranscriptionResult, error wrapping, translate branch, param forwarding)
- [x] Write audio_storage.py filesystem tests (save/copy/delete/cleanup/stats/get — real FS ops)

## F. Logging and Migration Tests
- [x] Write db_logging.py tests (DatabaseLogHandler.emit, close, connection lifecycle, setup_dual_logging)
- [x] Write migration.py tests (detect/run/rollback/verify; patch module constants LEGACY_*, not Path.home())

## G. End-to-End Test
- [x] Write E2E dictation pipeline test (real SQLite + storage, mocked audio/API/clipboard)

## H. Coverage Gate and Finalization
- [ ] Add per-module coverage thresholds to CI
- [ ] Run full test suite and verify all coverage targets met
- [ ] Validate OpenSpec change with `openspec validate 2026-08-01-test-safety-net`
