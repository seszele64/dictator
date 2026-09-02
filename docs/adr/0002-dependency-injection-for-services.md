# ADR 2: Dependency Injection for Services

## Status

Superseded by ADR 0003 (2026-09-02)

## Context

`DictationService` uses lazy property access to create database and audio storage instances:

```python
@property
def _database(self):
    if self._db is None:
        self._db = Database(...)
    return self._db
```

This pattern makes tests require `patch()` for dependency replacement,
creates implicit dependencies that aren't visible in the constructor, and
makes it difficult to inject custom implementations for testing edge cases.

## Decision

**As written, this ADR never landed.** The optional constructor parameters
for `database` / `audio_storage` alongside lazy singletons were not
implemented. Instead, S2 resolved the underlying problem differently:
module-level singletons (`_database` / `_audio_storage` globals with
getter/closers) were deleted and replaced with **per-command instances
constructed at the composition root**, with configuration passed explicitly
and connections closed deterministically.

That approach is recorded as ADR 0003 (Composition Root over Lazy
Singletons), which supersedes this ADR. Constructor injection was not
adopted; the remaining lazy `database` / `audio_storage` properties on
`DictationService` are S3 residue, scheduled to disappear with the
god-module splits.

## Consequences

- **Positive**: The problem this ADR targeted (hidden global singletons)
  is resolved - tests construct real per-command instances
- **Negative**: Constructor-injection ergonomics were never gained;
  `DictationService` tests still patch the lazy seams
- **Neutral**: Superseded before acceptance; kept for decision history

## Related Files

- `whisper_dictate/dictation.py` - service with the remaining lazy properties
- `whisper_dictate/app.py` - composition root (S2)
- `whisper_dictate/cli_helpers.py` - `with_database` per-command construction
- `tests/integration/test_dictation.py` - tests exercising the service
