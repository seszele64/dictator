# ADR 1: Centralized Test Doubles and Fixtures

## Status

Accepted (2026-09-02)

## Context

Tests frequently need mock database, storage, transcription, and recorder
objects. Manual mock configuration is error-prone and leads to incomplete
mocks, causing test failures. Each test that needs a mock database or
storage object must manually set up the methods, return values, and side
effects, which creates:

- Inconsistent mock behavior across tests
- Duplicated setup code
- High maintenance burden when interfaces change
- Test fragility where changes to the interface break multiple tests

This ADR was originally proposed as "Mock Factory Pattern for Async
Resources": `create_mock_database()` and `create_mock_audio_storage()`
factory functions in a root-level ``tests/helpers`` module, returning
pre-configured mocks for async interfaces.

## Decision

Record what actually exists: the suite standardizes its test doubles in
three centralized places instead of the originally proposed factory
functions.

1. **`tests/conftest.py` fixtures** — shared, pre-configured doubles and
   environment isolators, including `mock_config` (a complete `AppConfig`
   safe for tests), `real_db` / `real_db_config` (real initialized SQLite
   against temp directories), `env_isolator` (XDG/HOME/API-key environment
   isolation), and the module mocks installed in `sys.modules` before any
   import (sounddevice, soundfile, pydub) so audio backends are never
   loaded during tests.
2. **`tests/fakes.py`** — lightweight in-memory fakes implementing the real
   interfaces: `FakeRecorder` (scripted `AudioRecorder` stand-in that
   records `FakeRecorderCall`s) and `FakeTranscriptionProvider` (a
   `TranscriptionProvider` implementation returning scripted
   `FakeProviderCall` results).
3. **`tests/helpers/snapshot.py`** — CLI snapshot drift detection: recorded
   command outputs in `tests/snapshots/` are compared byte-for-byte so CLI
   regressions fail loudly.

The originally proposed `create_mock_database()` / `create_mock_audio_storage()`
factory functions were never built (they appear nowhere in the tree). The
suite has been synchronous since the asyncio purge, and S2 moved to
per-instance construction at the composition root, which made module-level
mock factories obsolete: each test either builds its own real instances
against temp paths (the S2 invariant) or composes `unittest.mock` objects
with the fixtures above. The helpers module the proposal referenced was
never created; the helpers live in the `tests/helpers/` package.

## Consequences

- **Positive**: Centralized double configuration - all shared mock/fake
  setup lives in a handful of reviewed places
- **Positive**: Single source of truth for default mock behavior
- **Positive**: Easy to update all tests when an interface changes (only
  one place to modify)
- **Positive**: Real-SQLite fixtures keep persistence tests honest without
  a separate mocking layer
- **Negative**: Additional test infrastructure to maintain
- **Negative**: Requires coordination between interface changes and
  fixture/fake updates

## Related Files

- `tests/conftest.py` - shared fixtures, env isolators, sys.modules audio mocks
- `tests/fakes.py` - FakeRecorder / FakeTranscriptionProvider
- `tests/helpers/snapshot.py` - CLI snapshot drift detection
