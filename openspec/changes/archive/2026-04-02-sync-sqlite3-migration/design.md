## Context

The whisper-dictate CLI application uses Python's `aiosqlite` library for database operations, but the application itself is synchronous CLI code that invokes these async operations via `asyncio.run()` 39+ times across 7 files. This creates a fundamental architectural mismatch:

1. `asyncio.run()` creates a **new event loop** each time it is called
2. `aiosqlite` spawns a background thread with its own event loop for async operations
3. The aiosqlite background thread is bound to the **first** event loop created
4. Subsequent calls to `asyncio.run()` create new (and eventually closed) loops, causing "RuntimeError: Event loop is closed"

This is not a configuration bug — it's a fundamental incompatibility between aiosqlite's threading model and the pattern of repeated `asyncio.run()` calls in a synchronous CLI.

**Current State:**
- `database.py` provides an async `Database` class wrapping aiosqlite
- All consumers call `asyncio.run(Database.method())` to use sync code paths
- WAL mode is enabled for crash recovery
- Schema migrations are managed via version tracking

**Constraints:**
- Must preserve WAL mode for crash recovery guarantees
- Must maintain schema migration logic
- Must preserve integrity check behavior
- CLI interface must remain unchanged
- Tests must pass after migration

## Goals / Non-Goals

**Goals:**
- Eliminate "Event loop is closed" runtime errors by replacing aiosqlite with sqlite3
- Maintain WAL mode for crash recovery (no data loss on crashes)
- Preserve all existing database functionality: schema migrations, integrity checks, connection management
- Minimal changes to application architecture — focus on the database layer
- No new external dependencies (sqlite3 is in Python stdlib)

**Non-Goals:**
- Not a performance optimization — sync sqlite3 may be slightly slower for concurrent reads
- Not changing the schema or data model
- Not modifying the CLI interface or user-facing behavior
- Not adding new database features (e.g., full-text search, JSON support)
- Not supporting async contexts (the CLI is synchronous)

## Decisions

### Decision 1: Replace aiosqlite with sqlite3

**Choice:** Use Python's standard library `sqlite3` for all database operations.

**Rationale:**
- Eliminates the async/threading complexity entirely
- sqlite3 is synchronous by design, matching the CLI's synchronous nature
- No `asyncio.run()` calls needed — direct function calls
- WAL mode works identically with sqlite3
- No external dependency to install or maintain

**Alternatives Considered:**
- **Keep aiosqlite + thread-local event loops**: Rejected — complex, fragile, still has edge cases with thread pools
- **Use aiosqlite with single event loop**: Rejected — requires refactoring CLI to run on one loop, major architectural change
- **Use asyncpg/SQLAlchemy**: Rejected — overkill for local SQLite, adds dependencies

### Decision 2: Maintain WAL Mode

**Choice:** Preserve `PRAGMA journal_mode=WAL` exactly as currently configured.

**Rationale:**
- WAL mode provides crash recovery guarantees — the primary data safety feature
- sqlite3 supports WAL mode natively and identically to aiosqlite
- No code changes needed for WAL — just pass the same PRAGMA

### Decision 3: Database Class Synchronization

**Choice:** Convert the `Database` class from async to synchronous methods, removing async context managers.

**Changes:**
```
# Before (async)
async def get_settings(self) -> dict[str, Any]:
    async with self._lock:
        async with self._connection.cursor() as cursor:
            await cursor.execute("SELECT ...")

# After (sync)
def get_settings(self) -> dict[str, Any]:
    with self._lock:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT ...")
```

**Rationale:**
- Direct mechanical conversion of async/await to synchronous calls
- `_lock` becomes `threading.Lock` (or remove if single-threaded context)
- `_connection` becomes a regular sqlite3.Connection
- `__aenter__`/`__aexit__` become `__enter__`/`__exit__`

### Decision 4: Connection Management

**Choice:** Use a module-level singleton pattern with lazy initialization (same as current).

**Rationale:**
- Maintains backward compatibility with existing `get_database()` calls
- sqlite3 connections are thread-safe but should be used from one thread
- Connection is created on first use, reused for all operations

### Decision 5: Remove with_database Decorator Entirely

**Choice:** Remove the `with_database` decorator entirely since no async context is needed with synchronous database operations.

**Before:**
```python
@with_database
async def foo(db, arg1):
    await db.set_setting(...)
```

**After:**
```python
def foo(db, arg1):
    db.set_setting(...)
```

**Rationale:**
- Eliminates decorator complexity entirely
- Callers simply use `get_database()` and call methods directly
- No async context means the decorator serves no purpose
- Context manager `with get_database() as db:` still works if cleanup is needed

### Decision 6: Test Suite Migration

**Choice:** Convert async test fixtures and tests to synchronous equivalents.

**Key Changes:**
- `@pytest.fixture` instead of `@pytest.fixture` with async
- `pytest.mark.asyncio` → standard pytest (sync tests)
- Remove async test infrastructure (event loop fixtures, async test markers)
- No event loop management in tests

**Rationale:**
- Tests should mirror production code patterns
- Simpler test setup, faster test execution
- No async test bugs

## Risks / Trade-offs

[Risk] **Behavioral Change: Synchronous Blocking**
→ The CLI will block during database operations. For local SQLite with WAL, this is typically sub-millisecond and acceptable for a CLI app. Mitigation: WAL ensures reads are non-blocking; writes are fast for typical CLI workloads.

[Risk] **Transaction Scope Changes**
→ Synchronous sqlite3 has different transaction boundaries. Mitigation: Review all transaction usage; ensure `connection.commit()` is called at appropriate points. The `autocommit` behavior differs from aiosqlite.

[Risk] **Connection Sharing**
→ sqlite3 connections cannot be shared across threads. Mitigation: Use connection from the main thread only; if threading is needed, use `check_same_thread=False` with caution or create per-thread connections.

[Risk] **Test Timing**
→ Sync tests run faster but may expose race conditions not visible in async tests. Mitigation: Add integration tests that exercise realistic CLI workflows end-to-end.

[Trade-off] **Removed Async Capability**
→ The application loses the ability to have truly concurrent database operations. For a CLI app, this is acceptable — the app is single-threaded and sequential.

## Migration Plan

### Phase 1: Update database.py (Day 1-2)
1. Replace `import aiosqlite` with `import sqlite3`
2. Convert `Database` class:
   - `async def` → `def`
   - `await cursor.execute()` → `cursor.execute()`
   - `async with` → `with`
   - `_connection` type: `aiosqlite.Connection` → `sqlite3.Connection`
3. Update `__init__.py` to export synchronous `Database`
4. Verify WAL mode still works: `PRAGMA journal_mode=WAL`

### Phase 2: Update Consumers (Day 2-4)
Files to update (remove `asyncio.run()` wrappers):
- `dictation.py` (~7 calls)
- `cli.py` (~9 calls)
- `toggle_dictate.py` (~15 calls)
- `cli_helpers.py` (remove with_database decorator)
- `db_logging.py`
- `audio_storage.py`

Pattern to remove:
```python
# Before
result = asyncio.run(db.get_setting(...))

# After
result = db.get_setting(...)
```

### Phase 3: Update Tests (Day 4-5)
1. Convert async fixtures to sync
2. Remove `pytest.mark.asyncio` decorators
3. Update test assertions as needed
4. Run full test suite

### Phase 4: Remove Dependencies (Day 5)
1. Remove `aiosqlite` from `pyproject.toml` / `requirements.txt`
2. Clean up any `async`-related imports
3. Verify `uv run pytest` passes

### Phase 5: Verification & Rollback Preparation (Day 5)
1. Commit changes to git branch with descriptive message
2. Run end-to-end CLI workflow test (record, transcribe, view history)
3. Verify WAL mode is functioning correctly on existing database
4. Document rollback steps (revert to aiosqlite implementation if needed)

### Rollback Strategy
- Keep git branch with pre-migration commit
- If issues arise, revert to aiosqlite implementation
- WAL mode ensures no data corruption risk

## Open Questions

1. **Thread Safety**: Should we use `check_same_thread=False` and a single connection, or create connections per-operation? Current aiosqlite approach needs review.

2. **Connection Timeout**: sqlite3 has a `timeout` parameter for locking. Should this be increased from default for safety?

3. **Error Handling**: aiosqlite may have different exception types. Need to verify all exception handling still works.

4. **Backup/Restore**: Any backup functionality using aiosqlite specifics needs review.
