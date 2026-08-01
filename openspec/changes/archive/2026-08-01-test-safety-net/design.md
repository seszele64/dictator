# Design: Phase 2 Test Safety Net

## Technical Approach

The approach is incremental and review-gated. Each group of work produces an atomic commit that is reviewed before proceeding. No production code is changed beyond minimal testability fixes (specifically, the database.py cross-thread sqlite3 access if the concurrency probe confirms the defect).

### Test Organization

Tests are reorganized from the current flat structure into:
- `tests/unit/` — fast, isolated tests using mocks (existing audio, clipboard, notifications, cli_helpers, transcription tests)
- `tests/integration/` — tests using real SQLite/filesystem (database, audio_storage, db_logging, migration, config)
- `tests/contract/` — ABC conformance tests (providers)
- `tests/e2e/` — full pipeline test

### Fixture Strategy

The hardened conftest.py provides:
- `real_db` — function-scoped, creates a real Database in a temp dir, auto-closes
- `real_db_config` — function-scoped, creates a DatabaseConfig pointing to a temp dir
- `db_singleton_reset` — function-scoped, resets any module-level Database singletons
- `env_isolator` — function-scoped, redirects XDG dirs, API keys, config paths to temp dirs
- `tmp_recordings_dir` — function-scoped, creates a temp recordings directory

The existing session-scoped `mock_cli_setup` and `patch_audio_modules` autouse fixtures are preserved but scoped correctly to avoid interfering with integration tests.

### Concurrency Documentation

The database.py threading.Lock serializes access but does NOT make the shared sqlite3.Connection thread-safe (sqlite3 connections are thread-bound by default). A test documents this behavior. If a minimal fix is approved (e.g., `check_same_thread=False`), it is applied; otherwise, the test is marked xfail with a clear reason.

## Architecture Decisions

### Decision: Use pytest-cov over raw coverage
- Pros: Integrates with pytest naturally, single command, well-supported
- Cons: Adds a dependency

### Decision: Real SQLite over in-memory
- Pros: Tests real file I/O, PRAGMA behavior, FK enforcement
- Cons: Slightly slower than in-memory
- Mitigation: Use `:memory:` where file I/O isn't tested, temp files where it is

### Decision: Module-constant patching for migration tests
- Pros: Avoids monkeypatching Path.home() which affects all modules
- Cons: Requires knowing the exact constant names
- Mitigation: Patch `whisper_dictate.migration.LEGACY_RECORDINGS_DIR` etc. directly

### Decision: No pytest-asyncio
- Pros: DB is synchronous, no async needed
- Cons: Spec 008 requires it (stale)
- Mitigation: Spec 008 is stale post-sqlite3-migration; will be addressed separately

## File Changes

- `pyproject.toml` — add pytest-cov to dev deps
- `.github/workflows/ci.yml` — add coverage step
- `tests/conftest.py` — harden with new fixtures
- `tests/unit/` — reorganized unit tests
- `tests/integration/` — new integration tests
- `tests/contract/` — new contract tests
- `tests/e2e/` — new e2e test
- `whisper_dictate/database.py` — conditional minimal testability fix (concurrency only)
