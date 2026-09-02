# ADR 3: Composition Root over Lazy Singletons

## Status

Accepted (2026-09-02)

Supersedes ADR 0002 (Dependency Injection for Services), which was never
implemented as written.

## Context

The codebase previously created databases and audio storage through
module-level singletons: a `_database` global with getter/closer helpers
(and the same pattern for `_audio_storage`), constructed from
module-level defaults on first access. This caused:

- Hidden global state: any caller could grab "the" database, with no
  ownership of its lifecycle
- Unclosed connections leaking across commands
- Configuration drift: singletons built from default `DatabaseConfig()`
  values ignored the user's configured paths unless every call site was
  carefully rewired
- Test fragility: singleton resets in fixtures and cross-test pollution
- Asymmetric close APIs (`close()` vs `close_database()`)

## Decision

All object construction happens at **entry points** (the composition
roots); services receive their dependencies and never reach for globals.

- `app.bootstrap()` is the single startup composition root: it owns
  `.env` loading (`load_dotenv`), configuration construction, and is the
  only startup path that mutates the environment.
- The CLI group callback composes per-command resources; every command
  that needs persistence gets a **fresh `Database` built via
  `with_database`**, which closes the connection in a `finally` block.
- The toggle's `main()` bootstraps its own config and its flows construct
  per-invocation `Database`/`AudioStorage` instances (see
  `get_db_and_storage`), each closed when its flow ends.
- There are no `_database` / `_audio_storage` module globals and no
  getter/closer helpers; `Database` exposes a public `config` accessor
  instead of a global lookup.

S3 residue: `DictationService` still lazily constructs its
`database` / `audio_storage` per instance (per-instance, not global - the
singleton problem is gone, but the lazy seam remains). The god-module
splits (S3) will remove that residue.

## Consequences

- **Positive**: Explicit ownership - whoever constructs a connection closes it
- **Positive**: Every instance honors the user's configured paths by construction
- **Positive**: Tests construct real per-command instances against temp
  paths; no singleton resets
- **Positive**: No hidden global state for a second caller to trip over
- **Negative**: More construction sites than a single shared instance
  (accepted: construction is cheap; correctness is not)
- **Negative**: The lazy service properties linger until S3

## Related Files

- `whisper_dictate/app.py` - bootstrap composition root (owns .env)
- `whisper_dictate/cli_helpers.py` - `with_database` (construct + close in finally)
- `whisper_dictate/database.py` - Database (public config accessor)
- `whisper_dictate/dictation.py` - DictationService (S3 residue: lazy properties)
