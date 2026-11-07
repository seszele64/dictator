# Spec Delta

## ADDED Requirements

### Requirement: Chat processing configuration is isolated from transcription settings

The system **SHALL** read the chat provider, model, base URL, API key, timeout, and preset prompt exclusively from `POST_PROCESS_PROVIDER`, `POST_PROCESS_MODEL`, `POST_PROCESS_BASE_URL`, `POST_PROCESS_API_KEY`, `POST_PROCESS_TIMEOUT`, and `POST_PROCESS_PROMPT`, and **MUST NOT** use `WHISPER_MODEL` or any other `WHISPER_*` value for chat processing.

#### Scenario: Transcription model is never inherited

- **GIVEN** `WHISPER_MODEL=whisper-1` and `POST_PROCESS_MODEL` is empty
- **WHEN** chat configuration is loaded
- **THEN** the chat model remains unset and is never set to `whisper-1`
- **AND** processing reports a missing chat model instead of calling the provider

#### Scenario: Dedicated chat model wins

- **GIVEN** `WHISPER_MODEL=whisper-large-v3` and `POST_PROCESS_MODEL=gpt-4o-mini`
- **WHEN** chat configuration is loaded
- **THEN** the chat model is `gpt-4o-mini`

#### Scenario: Dedicated chat API key wins

- **GIVEN** `POST_PROCESS_API_KEY=explicit-key` and `OPENAI_API_KEY=provider-key`
- **WHEN** chat configuration is resolved
- **THEN** the effective API key is `explicit-key`

#### Scenario: Transcription API key is not inherited

- **GIVEN** `WHISPER_API_KEY=whisper-only-key`, `POST_PROCESS_API_KEY` is empty, and the chat provider declares no key environment variable
- **WHEN** chat configuration is resolved
- **THEN** the effective chat API key is empty, not `whisper-only-key`

#### Scenario: Dedicated base URL overrides the provider default

- **GIVEN** `POST_PROCESS_PROVIDER=openai` and `POST_PROCESS_BASE_URL=https://gateway.example/v1`
- **WHEN** chat configuration is resolved
- **THEN** the effective base URL is `https://gateway.example/v1`

#### Scenario: Transcription timeout is never inherited

- **GIVEN** `WHISPER_TIMEOUT=5` and `POST_PROCESS_TIMEOUT` is absent
- **WHEN** chat configuration is loaded
- **THEN** the chat timeout is 60 seconds, not 5 seconds
- **AND** the transcription configuration still reports its own 5-second timeout

---

### Requirement: Chat model resolution has no default and no transcription fallback

The chat model **SHALL** have no built-in default, and an empty or whitespace-only `POST_PROCESS_MODEL` **MUST** be treated as not configured, producing an actionable error that names `POST_PROCESS_MODEL` rather than substituting any transcription or chat default. The system **MUST NOT** fall back to `PROVIDER_DEFAULTS[provider]["default_model"]`, `WHISPER_MODEL`, or any hardcoded model id when the chat model is missing.

#### Scenario: Missing model is rejected

- **GIVEN** `POST_PROCESS_MODEL` is absent
- **WHEN** the process command validates chat configuration
- **THEN** it reports that `POST_PROCESS_MODEL` must be set and does not call the provider

#### Scenario: Whitespace-only model is rejected

- **GIVEN** `POST_PROCESS_MODEL="   "`
- **WHEN** the process command validates chat configuration
- **THEN** it reports the model as missing and does not call the provider

#### Scenario: Provider table default model is never substituted

- **GIVEN** `POST_PROCESS_PROVIDER=openrouter` and `POST_PROCESS_MODEL` is empty
- **WHEN** the process command validates chat configuration
- **THEN** it reports the model as missing and the request is not sent
- **AND** neither `microsoft/mai-transcribe-2` nor `whisper-1` from `PROVIDER_DEFAULTS[...]["default_model"]` is used as the chat model

#### Scenario: Stored model is the stripped configured value

- **GIVEN** `POST_PROCESS_MODEL="  gpt-4o-mini  "` and a successful model response
- **WHEN** the result is persisted
- **THEN** the client request model and the stored `processed_model` are both `gpt-4o-mini`, with no surrounding whitespace

---

### Requirement: Chat provider facts resolve from the shared provider table

The system **SHALL** default `POST_PROCESS_PROVIDER` to `openai`, resolve the base URL from `POST_PROCESS_BASE_URL` and otherwise from the provider's declared default, and resolve the API key from `POST_PROCESS_API_KEY` and otherwise from the provider's declared key environment variable.

#### Scenario: Provider default base URL applies

- **GIVEN** `POST_PROCESS_PROVIDER=openrouter` and `POST_PROCESS_BASE_URL` is empty
- **WHEN** chat configuration is resolved
- **THEN** the OpenRouter base URL from the shared provider table is used

#### Scenario: Provider key environment variable is the fallback

- **GIVEN** `POST_PROCESS_PROVIDER=groq`, `POST_PROCESS_API_KEY` is empty, and `GROQ_API_KEY` is set
- **WHEN** chat configuration is resolved
- **THEN** the effective API key is the `GROQ_API_KEY` value

#### Scenario: Custom provider requires a base URL

- **GIVEN** `POST_PROCESS_PROVIDER=custom` and `POST_PROCESS_BASE_URL` is empty
- **WHEN** the process command validates chat configuration
- **THEN** it reports that `POST_PROCESS_BASE_URL` is required for a custom provider

#### Scenario: Keyless local provider is accepted

- **GIVEN** `POST_PROCESS_PROVIDER=local`, a local base URL, and no chat API key
- **WHEN** the process command validates chat configuration
- **THEN** validation succeeds without requiring a key

#### Scenario: Default provider is openai

- **GIVEN** no `POST_PROCESS_PROVIDER` value is set
- **WHEN** chat configuration is loaded
- **THEN** the provider is `openai`

#### Scenario: Unknown provider resolves to custom and requires a base URL

- **GIVEN** `POST_PROCESS_PROVIDER=bogus`, `POST_PROCESS_MODEL=gpt-4o-mini`, and `POST_PROCESS_BASE_URL` is empty
- **WHEN** the process command validates chat configuration
- **THEN** the provider resolves to `custom` and validation reports that `POST_PROCESS_BASE_URL` is required
- **AND** no model request is made

---

### Requirement: The chat request timeout is configurable, bounded, and independent

The system **SHALL** read the chat request timeout from `POST_PROCESS_TIMEOUT`, default it to 60 seconds when the variable is absent, pass the resolved value to the OpenAI client used for the request (`openai.OpenAI(..., timeout=config.timeout)`), and **MUST** fall back to 60 seconds with a logged warning when the value is non-numeric, zero, or negative. The timeout **MUST NOT** be derived from `WHISPER_TIMEOUT`.

#### Scenario: Timeout defaults to 60 seconds

- **GIVEN** `POST_PROCESS_TIMEOUT` is absent
- **WHEN** chat configuration is loaded and the client is constructed
- **THEN** `config.timeout` is `60.0` and the client is constructed with `timeout=60.0`

#### Scenario: Custom timeout reaches the client

- **GIVEN** `POST_PROCESS_TIMEOUT=15`
- **WHEN** processing runs
- **THEN** the constructed `openai.OpenAI` client receives `timeout=15.0`

#### Scenario: Non-numeric timeout falls back

- **GIVEN** `POST_PROCESS_TIMEOUT=abc`
- **WHEN** chat configuration is loaded
- **THEN** the timeout is `60.0`, a warning is logged, and no command fails at startup

#### Scenario: Zero and negative timeouts fall back

- **GIVEN** `POST_PROCESS_TIMEOUT` is `0` or `-5`
- **WHEN** chat configuration is loaded
- **THEN** the timeout is `60.0` and a warning is logged instead of constructing a client with a non-positive timeout

---

### Requirement: Chat configuration is validated lazily

Missing or invalid `POST_PROCESS_*` values **MUST NOT** prevent non-processing commands from loading configuration or running; validation **MUST** occur only when the process command is invoked.

#### Scenario: Non-processing commands ignore chat configuration

- **GIVEN** `POST_PROCESS_MODEL` is empty and no chat API key exists
- **WHEN** the user runs `whisper-dictate info` or `whisper-dictate history list`
- **THEN** the command succeeds without a chat-configuration error

#### Scenario: Processing validates at invocation time

- **GIVEN** the same incomplete chat configuration
- **WHEN** the user runs `whisper-dictate process --prompt "Summarize"`
- **THEN** the command reports the specific missing chat setting before any model request

---

### Requirement: Validation order is pinned so failures name the first missing setting

`validate_post_process_config()` **SHALL** evaluate settings in a fixed order — (1) non-empty stripped model, (2) provider resolution through `_resolve_provider_enum()`, (3) effective base URL from `POST_PROCESS_BASE_URL` or the provider default, (4) effective API key from `POST_PROCESS_API_KEY` or the provider key variable — and **MUST** report only the first failure. Unknown providers become `custom`; `custom` needs a base URL; `local`/`custom` are keyless; auth providers need a key.

#### Scenario: Missing model wins over a missing base URL

- **GIVEN** `POST_PROCESS_PROVIDER=custom`, `POST_PROCESS_MODEL` is empty, and `POST_PROCESS_BASE_URL` is empty
- **WHEN** chat configuration is validated
- **THEN** the error names `POST_PROCESS_MODEL` and does not mention the base URL

#### Scenario: Custom requires an explicit base URL even when a key exists

- **GIVEN** `POST_PROCESS_PROVIDER=custom`, a valid `POST_PROCESS_MODEL`, `POST_PROCESS_API_KEY=explicit-key`, and no `POST_PROCESS_BASE_URL`
- **WHEN** chat configuration is validated
- **THEN** the error names `POST_PROCESS_BASE_URL` and no request is made

#### Scenario: Local is keyless and uses its default base URL

- **GIVEN** `POST_PROCESS_PROVIDER=local`, a valid `POST_PROCESS_MODEL`, and no key variables
- **WHEN** chat configuration is validated
- **THEN** validation succeeds with the provider table's local base URL and the key step does not fail

#### Scenario: Auth provider missing its key fails after URL resolution

- **GIVEN** `POST_PROCESS_PROVIDER=groq`, a valid model, and neither `POST_PROCESS_API_KEY` nor `GROQ_API_KEY` set
- **WHEN** chat configuration is validated
- **THEN** the error names the API key variable and the base URL has already resolved successfully

---

### Requirement: Configuration and provider errors never expose secrets

Error messages and log lines produced by chat-configuration loading, validation, and client construction **SHALL** identify settings by variable name and **MUST NOT** include API-key values, full transcript text, or tracebacks.

#### Scenario: Missing key error omits the key value

- **GIVEN** `POST_PROCESS_PROVIDER=openai`, a valid model, and `OPENAI_API_KEY` unset
- **WHEN** validation fails and the error is logged and notified
- **THEN** the message names `POST_PROCESS_API_KEY`/`OPENAI_API_KEY` and contains no key value and no traceback

#### Scenario: Loader warnings do not log values

- **GIVEN** `POST_PROCESS_TIMEOUT=abc`
- **WHEN** the loader logs the fallback warning
- **THEN** the warning names the variable and the rejected value type but logs no API key and no transcript text

---

### Requirement: Chat configuration is documented in the example environment and README

`.env.example` and the README **SHALL** document every `POST_PROCESS_*` variable, its default, and the rule that the chat block is separate from the `WHISPER_*` transcription block, including why `WHISPER_MODEL` is never reused.

#### Scenario: Example environment documents the block

- **GIVEN** a user copies `.env.example` to `.env`
- **WHEN** they inspect it
- **THEN** they find a commented `POST_PROCESS_*` section with provider, model, base URL, API key, timeout, and preset prompt entries
- **AND** the section states that chat processing never inherits `WHISPER_MODEL`

#### Scenario: README explains the isolation

- **GIVEN** the README configuration section
- **WHEN** a user looks up `POST_PROCESS_MODEL`
- **THEN** it states that the value must name a chat model and is unrelated to `WHISPER_MODEL`
