# Proposal: Fix provider crash and API key handling

## Intent
Local and custom Whisper providers are advertised in config.py and `.env.example`, yet the CLI crashes with an unhandled `TypeError` on every command when `WHISPER_PROVIDER=local` or `custom`, keyless local/custom providers are still rejected for missing an API key, the advertised `WHISPER_TASK=translate` path always fails because an unsupported `language` argument is sent to the OpenAI translations endpoint, and pure database commands wrongly demand an API key. All four crashes were reproduced and live in code paths with no regression coverage.

## Scope
**In scope:**
- Fix the `env_var=None` crash in `load_config()` (`whisper_dictate/config.py:296-298`) so local/custom providers never pass `None` to `os.getenv`
- Permit keyless `local` and `custom` providers in `load_config()` (`config.py:300-304`) while still rejecting keyless openai/groq/together/deepinfra
- Preserve the existing graceful fallback to `CUSTOM` for invalid provider strings (`config.py:293-295`)
- Remove the unsupported `language` kwarg from `translations.create(...)` (`whisper_dictate/providers/openai_compatible.py:156-162`)
- Move API-key validation out of the `cli` group callback (`whisper_dictate/cli.py:110-120`) so non-transcription commands (`info`, `logs list`, `history list`, `audio cleanup`, `migrate --status`) run without a key; validate lazily only on transcription paths (`dictate`)
- Regression tests: unit tests for `load_config()` per provider (incl. keyless local/custom and invalid provider), a CliRunner test proving a non-transcription command runs without a key, and mocked-SDK tests covering both the translate and transcribe branches
- Docs: verify `.env.example` (already documents local/custom without keys) and update README provider table if it omits `local` / wrongly marks the API key as always required

**Out of scope:**
- New providers or provider configuration file formats (e.g., TOML/YAML config files)
- API retry/backoff, streaming transcription, or chunking support
- OpenAI SDK version changes or pinning
- Refactoring the shared `create_transcriber` vs `load_config` key resolution (only touched as needed for correctness)
- Changing `DictationService` internals, audio recording, or notification behavior

## Approach
Fix the config layer first by mirroring the already-correct guard in `create_transcriber()` (`transcription.py:127-136`): only call `os.getenv(env_var, "")` when `env_var` is truthy, and raise the missing-key `ValueError` only for providers that declare an auth environment variable (openai, groq, together, deepinfra) — providers with `env_var=None` (local, custom) are keyless by design and must load successfully. Keep the invalid-provider → `CUSTOM` fallback untouched.

Then make validation lazy in the CLI: `load_config()` gains a `require_api_key` flag (default `True` so non-CLI callers keep current behavior); the `cli` group callback calls it with `require_api_key=False` and stops constructing `DictationService` eagerly; the `dictate` command validates the key (with a friendly error message) before recording, while `info` and all DB-only commands run keyless. Fix the translate branch by dropping the `language` kwarg from `translations.create(...)` (the SDK has no such parameter) and logging that language hints are ignored for translation.

Finally add regression tests for every fixed path: parameterized `load_config()` tests per provider, a real-`load_config` CliRunner test for a non-transcription command with no key, and mocked-`OpenAI` tests asserting `translations.create` is called without `language` and `transcriptions.create` is called with it. Run `uv run pytest` and `uv run ruff check .` as gate.