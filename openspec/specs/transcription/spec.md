# transcription Specification

## Purpose
TBD - created by archiving change fix-provider-crash. Update Purpose after archive.
## Requirements
### Requirement: API-key validation is deferred to dictation commands
The system **SHALL** allow non-transcription CLI commands (`logs`, `history`, `audio`, `migrate`, `info`) to execute without an API key, and **MUST** validate the API key only when transcription is actually about to be performed (the `dictate` command).

#### Scenario: Database-only command runs without an API key
- Given: no API key is set in the environment and the configured provider requires authentication
- When: the user runs `whisper-dictate migrate --status` (or any `logs`/`history`/`audio` subcommand)
- Then: the command executes normally without a configuration error and exits successfully

#### Scenario: Dictate command reports missing key clearly
- Given: no API key is set in the environment and the configured provider requires authentication
- When: the user runs `whisper-dictate dictate`
- Then: a clear configuration error is printed to stderr and the command exits with a non-zero status

#### Scenario: Dictate command proceeds with keyless provider
- Given: `WHISPER_PROVIDER=local` and no API key is set in the environment
- When: the user runs `whisper-dictate dictate`
- Then: no API-key validation error is raised and dictation proceeds

---

### Requirement: Translate task uses only supported translation parameters
The system **SHALL** call the OpenAI-compatible translations endpoint when `WHISPER_TASK=translate` and **MUST NOT** pass unsupported keyword arguments (such as `language`) to `audio.translations.create`, while still passing `model`, `file`, `response_format`, and `temperature`.

#### Scenario: Translate with a language hint configured
- Given: `task=translate` and `language=en` on the provider
- When: `transcribe_audio()` is called on an audio file
- Then: `audio.translations.create` is invoked without a `language` argument and the request succeeds instead of raising a `TypeError`

#### Scenario: Translate with auto-detected language
- Given: `task=translate` and `language=None` on the provider
- When: `transcribe_audio()` is called on an audio file
- Then: `audio.translations.create` is invoked successfully without a `language` argument

#### Scenario: Transcribe branch keeps passing the language hint
- Given: `task=transcribe` and `language=en` on the provider
- When: `transcribe_audio()` is called on an audio file
- Then: `audio.transcriptions.create` is invoked with the `language` argument, preserving existing behavior

---

### Requirement: Regression tests cover translate and transcribe API calls
The system **SHALL** include automated regression tests with a mocked OpenAI client that verify the exact call signature used for both the translate and transcribe branches of `transcribe_audio()`.

#### Scenario: Mocked-SDK translate test
- Given: a mocked `openai.OpenAI` client and a provider configured with `task=translate`
- When: `transcribe_audio()` is called and the resulting API request is inspected
- Then: `translations.create` was called without a `language` keyword argument and no `TypeError` propagates

#### Scenario: Mocked-SDK transcribe test
- Given: a mocked `openai.OpenAI` client and a provider configured with `task=transcribe` and a language hint
- When: `transcribe_audio()` is called and the resulting API request is inspected
- Then: `transcriptions.create` was called with the configured `language` keyword argument

---

### Requirement: CLI regression test proves commands run keyless
The system **SHALL** include a CLI regression test using the real `load_config()` that verifies a non-transcription command succeeds when no API key is present (overriding the test-suite-wide mocked `load_config`).

#### Scenario: CliRunner executes a non-transcription command without a key
- Given: no API key is set in the environment, the real `load_config()` is used, and logging is stubbed
- When: the CLI runner invokes a non-transcription command such as `migrate --status`
- Then: the command exits with code 0 and no "API key not found" error is printed

