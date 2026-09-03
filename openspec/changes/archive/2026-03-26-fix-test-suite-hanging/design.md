# Design: fix-test-suite-hanging

## Context

The test suite hangs indefinitely when run as a complete suite, even though individual test files pass. This blocks CI/CD pipelines and makes iterative development painful.

**Root Cause Analysis:**
- Session-scoped `autouse` fixtures (`cleanup_sounddevice`, `cleanup_aiosqlite`) in `conftest.py` attempt to manage event loops after tests complete using `loop.run_until_complete()` and `asyncio.run()`
- pytest-asyncio creates its own event loop management, causing conflicts when combined with these fixtures
- `test_database_update.py` uses `asyncio.run()` directly in test functions instead of pytest-asyncio markers, creating nested event loops
- `test_audio_converter.py` uses direct module replacement in `sys.modules` which can interfere with event loop state
- No timeout protection means a single hanging test blocks the entire suite

**Current State:**
- `conftest.py` has two session-scoped autouse fixtures that try to clean up async resources after all tests complete
- No pytest configuration file exists (no `pytest.ini` or `pyproject.toml` for pytest settings)
- `reset_persistent_notification_state` fixture doesn't clear `_recording_notification`

## Goals / Non-Goals

**Goals:**
- Enable the full test suite to complete without hanging
- Ensure individual test files continue to pass independently
- Prevent event loop conflicts between pytest-asyncio and manual async handling
- Add timeout protection to catch hanging tests early
- Maintain test isolation and reproducibility

**Non-Goals:**
- Fix actual production code bugs (this is a test infrastructure fix)
- Change the test assertions or test coverage
- Modify the production async patterns (only test files change)
- Ensure tests pass if they were previously failing for other reasons

## Decisions

### Decision 1: Remove session-scoped autouse fixtures

**Choice:** Remove `cleanup_sounddevice` and `cleanup_aiosqlite` session-scoped autouse fixtures from `conftest.py`.

**Rationale:** These fixtures attempt cleanup after all tests complete by calling `loop.run_until_complete()` on an event loop that pytest-asyncio has already closed or is closing. This causes hangs because:
1. pytest-asyncio may have already cleaned up its event loops
2. Running `loop.run_until_complete()` on a closed loop raises `RuntimeError`
3. The `asyncio.get_running_loop()` call in `cleanup_aiosqlite` can return a loop that's in the process of shutting down

**Alternatives Considered:**
- *Keep fixtures but fix implementation*: Attempting to detect loop state adds complexity and still has race conditions
- *Make fixtures function-scoped*: Doesn't solve the fundamental conflict with pytest-asyncio's loop management
- *Use pytest-asyncio's built-in cleanup*: pytest-asyncio already handles event loop cleanup; redundant fixtures cause conflicts

**Implementation:** Delete lines 254-333 from `conftest.py`.

---

### Decision 2: Convert `asyncio.run()` to pytest-asyncio patterns

**Choice:** Replace all `asyncio.run()` calls in `test_database_update.py` with `@pytest.mark.asyncio` decorated async test functions using `await`.

**Rationale:** `asyncio.run()` creates a new event loop, runs the coroutine, and closes the loop. When pytest-asyncio is also managing event loops, this causes:
1. Nested event loops (the test runs inside pytest-asyncio's loop but creates its own)
2. Resource leaks as the inner loop closes before cleanup completes
3. Potential conflicts when mock async objects interact with real loop lifecycle

The tests are already written as async functions; they just need proper pytest-asyncio markers.

**Alternatives Considered:**
- *Use `pytest.mark.asyncio(loop_scope="function")`*: More verbose, strict mode makes missing markers an error anyway
- *Keep `asyncio.run()` and disable pytest-asyncio*: Defeats the purpose of using pytest-asyncio for consistency
- *Refactor to sync functions with `asyncio.run()` wrapping*: Same nesting problem

**Implementation:**
```python
# Before (test_database_update.py)
def test_update_transcript_text_only_mock(self, mock_database_with_update):
    result = asyncio.run(mock_database_with_update.update_transcript(...))

# After
@pytest.mark.asyncio
async def test_update_transcript_text_only_mock(self, mock_database_with_update):
    result = await mock_database_with_update.update_transcript(...)
```

---

### Decision 3: Configure pytest-asyncio in strict mode with function-scoped loops

**Choice:** Create `pytest.ini` with `asyncio_mode = strict` and `asyncio_default_fixture_loop_scope = function`.

**Rationale:** Strict mode enforces explicit `@pytest.mark.asyncio` markers, preventing accidental async tests that lack proper markers. Function-scoped loops ensure each test gets a fresh event loop, eliminating cross-test contamination.

**Alternatives Considered:**
- *Use `asyncio_mode = auto`*: Silently creates event loops for any async function, hiding potential marker issues
- *Session-scoped loop*: Shares loop across tests, risking state leakage between tests
- *Class-scoped loop*: Still risks state leakage within test classes

**Implementation:** Create `pytest.ini`:
```ini
[pytest]
asyncio_mode = strict
asyncio_default_fixture_loop_scope = function
```

---

### Decision 4: Add pytest-timeout with 30-second default

**Choice:** Configure `pytest-timeout` with `timeout = 30` in `pytest.ini`.

**Rationale:** Even with all fixes applied, a test could still hang due to unforeseen issues (deadlocks, infinite loops). A default timeout ensures the suite continues even if one test hangs, making debugging easier.

**Alternatives Considered:**
- *No timeout*: A single hanging test blocks the entire suite
- *Very short timeout (5s)*: May be too aggressive for legitimate long-running operations
- *Per-test timeouts only*: Doesn't protect against unexpected hangs

**Implementation:**
```ini
[pytest]
asyncio_mode = strict
asyncio_default_fixture_loop_scope = function
timeout = 30
```

Tests that legitimately need longer (e.g., integration tests) can use `@pytest.mark.timeout(120)`.

---

### Decision 5: Fix module mocking with `patch.dict()`

**Choice:** Change `test_audio_converter.py`'s `mock_pydub_in_sys_modules` fixture to use `patch.dict()` instead of direct module replacement.

**Rationale:** Direct module replacement via `sys.modules["pydub"] = mock_module` bypasses Python's import machinery and can leave stale references. `patch.dict()` properly uses the context manager protocol, ensuring cleanup happens even if a test fails.

**Current implementation (problematic):**
```python
sys.modules["pydub"] = mock_module
# ... later ...
sys.modules["pydub"] = original_pydub
```

**Better implementation:**
```python
@pytest.fixture(autouse=True)
def mock_pydub_in_sys_modules():
    with patch.dict(sys.modules, {"pydub": mock_module}):
        yield
```

**Alternatives Considered:**
- *Keep direct replacement with explicit try/finally*: Works but `patch.dict()` is the idiomatic approach
- *Use `pytest-mock`'s `mock.patch` on the import*: More complex, requires patching where it's used, not where it's defined
- *Use importlib.reload()*: Overkill for test mocking

---

### Decision 6: Enhance global state reset fixture

**Choice:** Add `_recording_notification` to the `reset_persistent_notification_state` fixture.

**Rationale:** The `PersistentNotification` class has a class variable `_recording_notification` that persists across tests. If one test sets it and doesn't clean up, subsequent tests may see stale state.

**Implementation:** Update `reset_persistent_notification_state` fixture in `conftest.py`:
```python
original_recording = notifications_module.PersistentNotification._recording_notification

# ... yield ...

notifications_module.PersistentNotification._recording_notification = original_recording
```

---

### Decision 7: Add function-scoped async cleanup fixture

**Choice:** Create a new function-scoped fixture for async resource cleanup as a replacement for the removed session-scoped fixtures.

**Rationale:** Some tests may legitimately need to clean up async resources (e.g., closing database connections). A function-scoped fixture with proper async cleanup using `request.addfinalizer()` ensures cleanup happens within the same event loop scope.

**Implementation:**
```python
@pytest.fixture
async def async_cleanup(request):
    """Function-scoped async cleanup within the test's event loop."""
    finalizers = []

    async def add_cleanup(coro):
        finalizers.append(coro)

    yield add_cleanup

    # Run finalizers in reverse order
    for finalizer in reversed(finalizers):
        try:
            await finalizer
        except Exception:
            pass
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        pytest                                │
│  ┌─────────────────────────────────────────────────────┐     │
│  │              pytest-asyncio plugin                   │     │
│  │  • Strict mode enforcement                           │     │
│  │  • Function-scoped event loops                       │     │
│  │  • Automatic cleanup on loop close                   │     │
│  └─────────────────────────────────────────────────────┘     │
│                           │                                  │
│  ┌─────────────────────────────────────────────────────┐     │
│  │                   conftest.py                         │     │
│  │  • patch_audio_modules (session-scoped, unchanged)  │     │
│  │  • reset_persistent_notification_state (function)    │     │
│  │  • async_cleanup (function-scoped, NEW)              │     │
│  └─────────────────────────────────────────────────────┘     │
│                           │                                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │test_database   │  │test_audio_     │  │   other tests  │  │
│  │_update.py      │  │converter.py    │  │                │  │
│  │                │  │                │  │                │  │
│  │@pytest.mark    │  │patch.dict()    │  │ (unchanged)    │  │
│  │.asyncio        │  │(NEW pattern)   │  │                │  │
│  │                │  │                │  │                │  │
│  │async def test()│  │                │  │                │  │
│  │  await ...     │  │                │  │                │  │
│  └────────────────┘  └────────────────┘  └────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐     │
│  │                 pytest-timeout                        │     │
│  │  • 30s default timeout                              │     │
│  │  • @pytest.mark.timeout() for overrides              │     │
│  └─────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

## Component Design

### Fixtures (conftest.py)

| Fixture | Scope | Purpose | Changes |
|---------|-------|---------|---------|
| `patch_audio_modules` | session | Mock sounddevice/soundfile before imports | None |
| `reset_persistent_notification_state` | function | Clear PersistentNotification state | Add `_recording_notification` |
| `async_cleanup` | function | NEW: Function-scoped async cleanup | Add new fixture |
| `cleanup_sounddevice` | session | REMOVED | Delete |
| `cleanup_aiosqlite` | session | REMOVED | Delete |

### pytest.ini Configuration

```ini
[pytest]
asyncio_mode = strict
asyncio_default_fixture_loop_scope = function
timeout = 30
```

### Test File Changes

**test_database_update.py:**
- Add `@pytest.mark.asyncio` to all async test methods
- Replace `asyncio.run(...)` with `await ...`
- Change `def` to `async def` for test methods

**test_audio_converter.py:**
- Replace direct `sys.modules` manipulation with `patch.dict()` in fixture

## Data Flow: Async Resource Management

### Before (Problematic)
```
Test Suite Start
       │
       ▼
┌──────────────────┐
│ Session-scoped  │
│ cleanup_sounddev│◄────── Creates new event loop after tests
│ ice/aiosqlite   │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ pytest-asyncio   │
│ session loop     │ ◄──── Conflict: loop already closed/closing
└──────────────────┘
       │
       ▼
    HANG
```

### After (Fixed)
```
Test Suite Start
       │
       ▼
┌──────────────────┐
│ Session-scoped   │
│ patch_audio_     │
│ modules          │ ◄──── Only mocks sys.modules, no event loops
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ pytest-asyncio   │
│ function loops   │ ◄──── Fresh loop per test, automatic cleanup
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ Each test runs   │
│ with its own     │
│ event loop       │
└──────────────────┘
       │
       ▼
    Complete
```

## Error Handling

### Timeout Behavior
- Default 30s timeout applies to all tests
- Hanging tests are terminated with `pytest_TIMEOUT_ exceeded`
- Other tests continue executing
- Timeout errors are reported but don't prevent remaining tests from running

### Event Loop Conflicts
- Strict mode catches missing `@pytest.mark.asyncio` markers at collection time
- Tests without proper markers fail immediately with clear error message
- No more silent hangs from event loop conflicts

### Cleanup Failures
- If async cleanup fails, errors are caught and logged
- Test failure takes precedence over cleanup errors
- Finalizers run in reverse order to respect dependencies

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Some tests legitimately need session-scoped cleanup | Low | Medium | Tests should use function-scoped fixtures; if truly needed, add a new non-autouse session fixture |
| 30s timeout is too short for some tests | Medium | Low | Use `@pytest.mark.timeout(120)` for specific slow tests |
| Strict mode catches tests that weren't running before | Medium | Low | These tests were likely broken/incomplete; explicit is better |
| patch.dict() changes mock behavior | Low | Low | `patch.dict()` is semantically equivalent for this use case |

## Migration Plan

1. **Create pytest.ini** with asyncio strict mode, function-scoped loop, and 30s timeout
2. **Modify conftest.py:**
   - Remove `cleanup_sounddevice` session-scoped autouse fixture (lines 254-269)
   - Remove `cleanup_aiosqlite` session-scoped autouse fixture (lines 272-333)
   - Add `_recording_notification` to `reset_persistent_notification_state`
   - Add `async_cleanup` function-scoped fixture
3. **Modify test_database_update.py:**
   - Add `@pytest.mark.asyncio` to all async test methods in `TestUpdateTranscript`
   - Change `asyncio.run(...)` to `await ...`
4. **Modify test_audio_converter.py:**
   - Change `mock_pydub_in_sys_modules` to use `patch.dict()`
5. **Verify:**
   - Run individual test files to confirm they pass
   - Run full suite to confirm it completes without hanging
   - Run `pytest --collect-only` to verify strict mode markers

**Rollback:** If issues occur, revert conftest.py to keep session-scoped fixtures and add `asyncio_mode = auto` to pytest.ini (less strict). This is a progressive enhancement.

## Open Questions

1. **Should we keep the `atexit.register(_cleanup_sounddevice)` in conftest.py?** It runs after pytest exits, so it shouldn't cause hangs, but it may be unnecessary if sounddevice is mocked during tests.

2. **Do any tests actually need the removed session-scoped cleanup?** Initial analysis suggests no, but if issues arise after removal, we may need to investigate specific tests that use sounddevice or aiosqlite directly.

3. **Should pytest-timeout be configured via `pyproject.toml` instead of `pytest.ini`?** Since there's no existing pytest configuration, either works. `pyproject.toml` is more modern but `pytest.ini` is simpler for pytest-specific settings.
