# Design: Fix provider crash and API key handling

## Technical Approach

Four independent defects are fixed in three layers, each with dedicated regression tests:

1. **Config layer** (`whisper_dictate/config.py:287-304`): The duplicate key-resolution logic in `load_config()` is inconsistent with `create_transcriber()` (`transcription.py:127-136`), which already guards `if env_var:` correctly and supplies a dummy key for `local`. Fix `load_config()` to mirror that behavior: guard the env-var lookup, and only raise the missing-key `ValueError` for providers that declare an auth env variable.
2. **CLI layer** (`whisper_dictate/cli.py:100-120`): The group callback currently calls `load_config()` (which can raise) and constructs `DictationService` (which builds an OpenAI client) eagerly for every subcommand. Introduce `load_config(require_api_key=True)`; the callback calls it with `require_api_key=False` and defers service construction to the commands that need it (`dictate`, `info`).
3. **Provider layer** (`whisper_dictate/providers/openai_compatible.py:143-162`): The translate branch passes `language=self._language`, a parameter that does not exist on `audio.translations.create` (verified against installed openai 2.30.0: params are `file, model, prompt, response_format, temperature, ...`). Remove the kwarg and log that language hints are ignored for translation.

## Architecture Decisions

### Decision: Treat absence of `env_var` in PROVIDER_DEFAULTS as "key not required"
- Pros: Single source of truth in `PROVIDER_DEFAULTS`; automatically covers future keyless providers; matches existing `create_transcriber()` behavior so both paths stay consistent
- Cons: Implicit coupling between auth requirement and env-var declaration — a provider that needs a key but forgets to declare `env_var` silently becomes keyless

### Decision: Add `require_api_key: bool = True` parameter to `load_config()`
- Pros: Minimal API change; default preserves behavior for existing callers and tests; the CLI can keep one call site with a clear explicit flag
- Cons: Another boolean parameter; validation policy is split between config loading and the CLI entry point

### Decision: Defer `DictationService` construction out of the `cli` group callback
- Pros: Non-transcription commands never construct an OpenAI client or AudioRecorder; true laziness rather than merely suppressing the error
- Cons: `info` must construct the service itself (it already tolerates an empty key because `get_system_info()` does not use the transcriber); a small helper or per-command construction is needed

### Decision: Key validation for `dictate` happens at command start, not inside `DictationService.__init__`
- Pros: `dictate` prints the existing friendly "Configuration error: API key not found" message via the existing `except ValueError` handling instead of an unhandled traceback; `info` and DB commands are unaffected by construction
- Cons: In-process callers of the service (tests, future UIs) are not protected — acceptable because `create_transcriber` already tolerates empty keys

## Data Flow

```text
cli group callback ── load_config(require_api_key=False) ── config stored in ctx.obj
        │
        ├─ info ── construct DictationService(keyless OK) ── get_system_info()
        ├─ logs/history/audio/migrate ── database only, no provider, no key needed
        └─ dictate ── validate api key (raise ValueError if required provider lacks key)
                    ── construct DictationService ── record → transcribe/translate
```

## File Changes

- `whisper_dictate/config.py` — guard `os.getenv` against `env_var=None`; raise missing-key `ValueError` only for auth-requiring providers; add `require_api_key` parameter to `load_config()`
- `whisper_dictate/cli.py` — call `load_config(require_api_key=False)` in group callback; construct `DictationService` per-command (`dictate`, `info`); keep the existing `except ValueError` handling for the `dictate` key check
- `whisper_dictate/providers/openai_compatible.py` — drop `language=` from `translations.create(...)`; add debug log noting language is ignored for translation
- `tests/test_config.py` (new) — parameterized `load_config()` tests across all providers incl. keyless `local`/`custom` and invalid provider string
- `tests/test_cli.py` (new) — CliRunner test running a non-transcription command with no API key, using the real `load_config()` (must override the session-scoped `mock_cli_setup` autouse patch in `tests/conftest.py:21-49`)
- `tests/test_transcription.py` — extend with mocked-`OpenAI` tests for translate (no `language` kwarg) and transcribe (with `language` kwarg) branches
- `README.md` — provider table (line ~433): include `local` provider and note API key is not required for `local`/`custom`
- `.env.example` — verify only; already documents `local`/`custom` keyless usage and `WHISPER_TASK`

## Risks / Mitigations

- **Risk**: Removing `language` from translations changes user-expectation for language control on translate.
  **Mitigation**: The translations endpoint cannot accept the parameter (SDK-level); log it at debug level so users understand, and keep the parameter for the transcribe branch.
- **Risk**: Making `load_config` lenient could mask genuine misconfiguration for key-requiring providers.
  **Mitigation**: The missing-key `ValueError` is preserved for `openai`/`groq`/`together`/`deepinfra`; only `local`/`custom`/unknown providers are keyless.
- **Risk**: Tests relying on the session autouse `load_config` mock may be affected by new real-config CLI tests.
  **Mitigation**: Real-config tests re-patch `whisper_dictate.cli.load_config` at test scope; document in a task.