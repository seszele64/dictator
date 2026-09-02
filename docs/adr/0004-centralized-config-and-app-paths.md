# ADR 4: Centralized Config and App Paths

## Status

Accepted (2026-09-02)

## Context

Path and environment handling was scattered:

- `config.py` ran `load_dotenv()` at module import time, so a bare
  `import whisper_dictate.config` rewrote `os.environ` (a side-effect
  import) and made configuration depend on import order.
- XDG directory resolution and legacy dotfile locations were duplicated:
  `migration.py` and the toggle each knew where the legacy
  `toggle_state` / `toggle.pid` / `toggle.wav`-style files lived, so the
  migration's source paths and the toggle's runtime paths could drift.

## Decision

1. **`AppPaths` is the single source of truth for filesystem locations.**
   All XDG data/state/config homes, the log directory and log file, and
   the legacy dotfile paths are resolved through `AppPaths`. Both the
   migration (its source files) and the toggle (its runtime
   `STATE_FILE` / `PID_FILE` / `AUDIO_FILE`) resolve the same legacy
   dotfiles through `AppPaths`, so the migration's sources and the
   toggle's runtime files can never drift apart.
2. **`load_dotenv` moved into the composition root.** Only
   `app.bootstrap()` loads `.env`; importing the config module (or calling
   `load_config()`) is side-effect-free and env-pure. Entry points that
   need dotenv behavior call the composition root.

## Consequences

- **Positive**: One place to reason about every filesystem location
- **Positive**: Migration sources and toggle runtime files are pinned
  together by construction
- **Positive**: Importing configuration no longer mutates the environment
  (pinned by subprocess-based tests in `tests/unit/test_config.py`)
- **Negative**: Every path consumer must go through `AppPaths` - a new
  path literal introduced elsewhere is a regression the type system will
  not catch

## Related Files

- `whisper_dictate/config.py` - AppPaths + AppConfig / load_config (env-pure)
- `whisper_dictate/app.py` - bootstrap: the only load_dotenv site
- `whisper_dictate/migration.py` - legacy source paths via AppPaths
- `whisper_dictate/toggle.py` - runtime STATE/PID/AUDIO files via AppPaths
