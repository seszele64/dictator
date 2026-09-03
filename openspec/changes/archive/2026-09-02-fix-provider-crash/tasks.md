# Tasks

## 1. Fix `load_config()` provider crash (`config.py`)

- [x] 1.1 Guard the env-var lookup: change `config.py:297-298` so `os.getenv(env_var, "")` is only called when a provider env var exists — e.g. resolve with `if env_var:` (mirroring `create_transcriber()` at `transcription.py:130-132`) instead of `defaults.get("env_var", "OPENAI_API_KEY")`
- [x] 1.2 Permit keyless providers: only raise the missing-key `ValueError` (`config.py:300-304`) when the provider declares an auth env var (openai/groq/together/deepinfra); `local`/`custom` must load with an empty key
- [x] 1.3 Add `require_api_key: bool = True` parameter to `load_config()` so the CLI can defer validation while other callers keep current behavior
- [x] 1.4 Verify the invalid-provider → `WhisperProvider.CUSTOM` fallback (`config.py:293-295`) still works with the new keyless logic (unknown provider = keyless custom)

## 2. Make API-key validation lazy in the CLI (`cli.py`)

- [x] 2.1 In the `cli` group callback (`cli.py:110-120`): call `load_config(require_api_key=False)` and store config on `ctx.obj` without constructing `DictationService`
- [x] 2.2 Construct `DictationService(config)` inside the `dictate` command after validating the API key; re-use the existing `except ValueError` path so a missing key prints "Configuration error: API key not found" and exits 1
- [x] 2.3 Construct `DictationService(config)` inside the `info` command (keyless OK — `get_system_info()` does not use the transcriber)
- [x] 2.4 Confirm DB-only commands (`logs`, `history`, `audio`, `migrate`) never touch provider config or the service and run without a key

## 3. Fix the translate branch (`providers/openai_compatible.py`)

- [x] 3.1 Remove the `language=self._language` kwarg from `audio.translations.create(...)` (`openai_compatible.py:156-162`)
- [x] 3.2 Add a debug log when `task=translate` that a configured language hint is ignored (translations endpoint has no `language` parameter)
- [x] 3.3 Ensure the transcribe branch (`openai_compatible.py:176-182`) continues passing `language` unchanged

## 4. Regression tests

- [x] 4.1 Create `tests/test_config.py` with parameterized `load_config()` unit tests: each provider (openai, groq, together, deepinfra, local, custom, invalid-string) with and without keys — keyless local/custom and invalid providers must not raise; auth providers without keys must raise `ValueError`; use monkeypatch to control env vars
- [x] 4.2 Create `tests/test_cli.py` with a CliRunner test: run a non-transcription command (e.g. `migrate --status`) with no API key and the real `load_config()`, asserting exit code 0 and no "API key not found" output (must override the session-autouse mocked `load_config` from `tests/conftest.py:21-49`; patch `whisper_dictate.cli.setup_logging`)
- [x] 4.3 Extend `tests/test_transcription.py` with mocked-`OpenAI` (reuse `mock_openai_client` fixture pattern from `tests/conftest.py:253-266`): task=translate asserts `translations.create` called without `language`; task=transcribe asserts `transcriptions.create` called with `language`
- [x] 4.4 Add a `dictate`-path regression check that a keyless `local` provider passes validation (no key error) — at unit level to avoid recording in tests

## 5. Documentation

- [x] 5.1 Verify `.env.example` (already documents local/custom keyless sections and `WHISPER_TASK`) — update only if a section is misleading
- [x] 5.2 Update `README.md` provider table (~lines 429-454): add the `local` provider value and note that `local`/`custom` do not require an API key

## 6. Quality gates

- [x] 6.1 Run full suite: `uv run pytest` — all tests pass
- [x] 6.2 Run linter: `uv run ruff check .` — clean
- [x] 6.3 Manually smoke-test: `WHISPER_PROVIDER=local` → `whisper-dictate migrate --status` and `whisper-dictate logs list` run without tracebacks
