# Proposal: Phase 2 Test Safety Net

## Intent
The project has 258 passing tests but critical modules have dangerously low coverage (database.py 45%, db_logging.py 0%, migration.py 17%). Tests are flat-organized with no real SQLite integration tests, no coverage gate in CI, and fragile session-scoped mocks. This change establishes a proper test safety net before any structural refactoring in Phase 3.

## Scope

**In scope:**
- Add pytest-cov to dev dependencies and coverage collection to CI (no threshold initially)
- Reorganize tests into unit/, integration/, contract/, e2e/ directories
- Harden conftest.py with shared real-DB fixtures and environment isolation
- Deduplicate overlapping test_history.py and test_cli_database_lifecycle.py
- Add real SQLite integration tests for database.py (schema, CRUD, transactions, FK cascade, maintenance, concurrency probe)
- Add config.py tests (load, validation, env fallback, XDG paths)
- Add provider contract tests for openai_compatible.py (ABC conformance, error wrapping, translate branch)
- Add audio_storage.py filesystem tests (real temp-dir save/copy/delete/cleanup/stats)
- Add db_logging.py tests (DatabaseLogHandler emit/close/lifecycle, setup_dual_logging)
- Add migration.py tests (detect/run/rollback/verify with module-constant patching)
- Add one E2E dictation pipeline test (real SQLite + storage, mocked audio/API/clipboard)
- Add per-module coverage gates to CI after tests are written
- Conditional minimal testability fix for database.py cross-thread sqlite3 access (only if concurrency probe confirms the defect)

**Out of scope:**
- Production refactoring beyond minimal testability fixes (deferred to Phase 3)
- Streaming transcription (Phase 4)
- SQLite FTS (Phase 4)
- Reintroducing async/aiosqlite (explicitly rejected — DB is now synchronous)
- pytest-asyncio (no longer needed since DB migration to synchronous sqlite3)
- Modifying spec 008's pytest-asyncio requirements (that spec is stale and will be addressed separately)

## Approach
Implement in 8 reviewed groups (A through H), each with an atomic commit. Start with tooling and test infrastructure (Groups A-B), then build module-specific tests (Groups C-F), then E2E (Group G), then coverage gates (Group H). Each group is reviewed before committing. The concurrency defect in database.py (threading.Lock does not make shared sqlite3.Connection thread-safe) is documented via a test; a minimal production fix is applied only with explicit approval.
