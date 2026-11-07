# configuration Specification

## Purpose
TBD - created by archiving change fix-provider-crash. Update Purpose after archive.

## Requirements

### Requirement: Provider environment variable resolution tolerates missing env vars
The system **SHALL** resolve the API key from the provider's declared environment variable only when that variable is a non-empty string, and **MUST NOT** pass `None` to `os.getenv` during configuration loading.

#### Scenario: Local provider declares no API key environment variable
- Given: `WHISPER_PROVIDER=local` and no API key is set in the environment
- When: `load_config()` is called
- Then: configuration loading completes without a `TypeError` and returns an `AppConfig` with an empty API key

#### Scenario: Custom provider declares no API key environment variable
- Given: `WHISPER_PROVIDER=custom` and no API key is set in the environment
- When: `load_config()` is called
- Then: configuration loading completes without a `TypeError` and returns an `AppConfig` with an empty API key

#### Scenario: Key-requiring provider resolves its declared environment variable
- Given: `WHISPER_PROVIDER=groq` and `GROQ_API_KEY` is set in the environment
- When: `load_config()` is called
- Then: the resolved `GROQ_API_KEY` value is used as the API key

---

### Requirement: Keyless local and custom providers load without an API key
The system **SHALL** accept configurations for providers that do not require authentication (`local`, `custom`) even when no API key is present, and **MUST** raise a configuration error for authentication-requiring providers (`openai`, `groq`, `together`, `deepinfra`, `openrouter`) only when no key is available.

#### Scenario: Local provider runs without any API key
- Given: `WHISPER_PROVIDER=local` and no API key is set in the environment
- When: `load_config()` is called
- Then: configuration loading succeeds without raising a "API key not found" error

#### Scenario: Custom provider runs without any API key
- Given: `WHISPER_PROVIDER=custom`, `WHISPER_BASE_URL` is set, and no API key is set in the environment
- When: `load_config()` is called
- Then: configuration loading succeeds without raising a "API key not found" error

#### Scenario: Key-requiring provider still fails without an API key
- Given: `WHISPER_PROVIDER=openai` and no API key is set in the environment
- When: `load_config()` is called
- Then: a `ValueError` describing the missing API key is raised

---

### Requirement: Invalid provider strings fall back to custom
The system **SHALL** treat an unrecognized provider string as the `custom` provider during configuration loading so that unknown values fail gracefully instead of crashing.

#### Scenario: Unknown provider value in environment
- Given: `WHISPER_PROVIDER=not-a-real-provider` and no API key is set in the environment
- When: `load_config()` is called
- Then: the provider is treated as `custom`, configuration loading completes without an exception, and no API key is required

---

### Requirement: Regression tests cover provider configuration loading
The system **SHALL** include automated regression tests that exercise `load_config()` for every provider with and without API keys, including keyless `local`/`custom` and invalid provider strings.

#### Scenario: Parameterized load_config tests run
- Given: a test suite covering `openai`, `groq`, `together`, `deepinfra`, `openrouter`, `local`, `custom`, and an invalid provider string with controlled environment variables
- When: the test suite is executed
- Then: keyless local/custom and invalid-provider cases pass without exceptions, and key-requiring providers without keys still raise `ValueError`

### Requirement: Every provider declares a default transcription model
The system **SHALL** declare a `default_model` for every entry in `PROVIDER_DEFAULTS`, and **MUST** resolve that provider-specific default whenever no explicit model is configured. The OpenRouter default **MUST** be a valid namespaced model identifier accepted by OpenRouter, the OpenAI default **MUST** remain `whisper-1`, and the Groq default **MUST** be `whisper-large-v3`.

#### Scenario: OpenRouter resolves to a valid default model
- Given: `WHISPER_PROVIDER=openrouter`, `OPENROUTER_API_KEY` is set, and `WHISPER_MODEL` is not set
- When: `load_config()` is called
- Then: `config.openai.model` equals the OpenRouter default `microsoft/mai-transcribe-2`, which contains a `vendor/model` namespace
- And: the resolved model is what `create_transcriber()` passes to the provider

#### Scenario: Direct WhisperConfig construction applies the provider default
- Given: no environment variables are set
- When: `WhisperConfig(provider="openrouter")` is constructed directly
- Then: `config.model` equals `microsoft/mai-transcribe-2` rather than the generic `whisper-1`

#### Scenario: OpenAI behavior is unchanged
- Given: `WHISPER_PROVIDER=openai`, `OPENAI_API_KEY` is set, and `WHISPER_MODEL` is not set
- When: `load_config()` is called
- Then: `config.openai.model` equals `whisper-1`, exactly as before this change

#### Scenario: Groq resolves to its provider default
- Given: `WHISPER_PROVIDER=groq`, `GROQ_API_KEY` is set, and `WHISPER_MODEL` is not set
- When: `load_config()` is called
- Then: `config.openai.model` equals `whisper-large-v3`
- And: no `vendor/model` namespace is required for Groq

#### Scenario: Providers without a verified canonical id keep their current default
- Given: `WHISPER_PROVIDER` is `together`, `deepinfra`, `local`, or `custom` and `WHISPER_MODEL` is not set
- When: `load_config()` is called
- Then: the resolved model equals that provider's declared `default_model`, which preserves the pre-change `whisper-1` behavior
- And: an unknown provider string resolves through the existing `custom` fallback and receives the `custom` default

---

### Requirement: Explicit model configuration overrides the provider default
The system **SHALL** treat a non-empty `WHISPER_MODEL` value as the effective model for the selected provider and **MUST NOT** replace it with a provider default. Leading and trailing whitespace **MUST** be ignored, and an empty or whitespace-only value **MUST** be treated as "not configured" so the provider default applies.

#### Scenario: Explicit non-empty model wins
- Given: `WHISPER_PROVIDER=openrouter` and `WHISPER_MODEL=openai/whisper-1`
- When: `load_config()` is called
- Then: `config.openai.model` equals `openai/whisper-1`
- And: the OpenRouter default `microsoft/mai-transcribe-2` is not substituted

#### Scenario: Blank WHISPER_MODEL falls back to the provider default
- Given: `WHISPER_PROVIDER=openrouter` and `WHISPER_MODEL=` is present but empty (as in a copied `.env.example`)
- When: `load_config()` is called
- Then: `config.openai.model` equals `microsoft/mai-transcribe-2`

#### Scenario: Whitespace-only WHISPER_MODEL falls back to the provider default
- Given: `WHISPER_PROVIDER=openrouter` and `WHISPER_MODEL="   "`
- When: `load_config()` is called
- Then: `config.openai.model` equals `microsoft/mai-transcribe-2` with no whitespace preserved

#### Scenario: Explicit override is trimmed
- Given: `WHISPER_PROVIDER=openai` and `WHISPER_MODEL="  whisper-large-v3  "`
- When: `load_config()` is called
- Then: `config.openai.model` equals `whisper-large-v3`

---

### Requirement: Effective models are validated at configuration load
The system **SHALL** validate the effective model when the selected provider is `openrouter` and **MUST** raise `ValueError` at configuration load when it has no `vendor/model` namespace. The message **MUST** name the invalid model and include at least one valid example. Other providers **MUST NOT** be namespace-validated. Any provider **MUST** reject an empty effective model with an actionable `ValueError`.

#### Scenario: Namespaced OpenRouter override is accepted
- Given: `WHISPER_PROVIDER=openrouter` and `WHISPER_MODEL=microsoft/mai-transcribe-2`
- When: `load_config()` is called
- Then: configuration loads successfully and `config.openai.model` equals `microsoft/mai-transcribe-2`

#### Scenario: Un-namespaced OpenRouter override fails fast
- Given: `WHISPER_PROVIDER=openrouter` and `WHISPER_MODEL=whisper-1`
- When: `load_config()` is called
- Then: a `ValueError` is raised whose message contains `whisper-1` and at least one valid namespaced example
- And: the failure occurs before any transcription request is attempted

#### Scenario: Non-OpenRouter providers are exempt from namespace validation
- Given: `WHISPER_PROVIDER=groq` and `WHISPER_MODEL=whisper-large-v3` (no slash)
- When: `load_config()` is called
- Then: configuration loads successfully and `config.openai.model` equals `whisper-large-v3`

#### Scenario: Custom provider models are not namespace-validated
- Given: `WHISPER_PROVIDER=custom`, `WHISPER_BASE_URL` is set, and `WHISPER_MODEL=base.en`
- When: `load_config()` is called
- Then: configuration loads successfully and `config.openai.model` equals `base.en`

#### Scenario: Empty effective model is rejected for every provider
- Given: any `WHISPER_PROVIDER` value and an effective model of `""` — either supplied directly to `validate_model()`, or reached through the `WhisperConfig` model validator when the `PROVIDER_DEFAULTS` table entry is bypassed or empty (the normal `resolve_model()` path always substitutes a default, so this path is a defense-in-depth guard)
- When: `validate_model(provider, "")` runs directly, or the `WhisperConfig` validator calls it with that empty value
- Then: a `ValueError` is raised whose message names the provider and tells the user to set `WHISPER_MODEL` or rely on the provider default
- And: the failure occurs during configuration validation, before any transcription request

---

### Requirement: The transcriber factory defensively resolves the model
`create_transcriber()` **SHALL** pass a resolved effective model to the provider even for configurations that skipped validation (`model_construct()`), and **MUST** be idempotent for already-resolved configs. This defense **MUST** cover the provider call only and **MUST NOT** be described as repairing `config.openai.model` for direct readers such as transcript history; that limitation **MUST** be documented in `design.md`.

#### Scenario: Already-resolved config passes through unchanged
- Given: a `WhisperConfig` built through normal validation with `WHISPER_PROVIDER=openrouter` and no explicit model, so `config.model` is already `microsoft/mai-transcribe-2`
- When: `create_transcriber(config)` is called
- Then: the provider receives `model="microsoft/mai-transcribe-2"`, unchanged
- And: the factory performs no second visible resolution

#### Scenario: Bypassed config with an empty model is resolved at the factory
- Given: a `WhisperConfig` produced with `WhisperConfig.model_construct(provider="openrouter", model="")`, so no validator ran
- When: `create_transcriber(config)` is called
- Then: the provider receives `model="microsoft/mai-transcribe-2"`
- And: the factory does not mutate `config.model`, so the documented limitation still applies to direct readers such as transcript history

---

### Requirement: Model resolution is covered by regression tests
The change **SHALL** add automated unit tests that exercise model resolution for every provider, proving the OpenRouter and Groq defaults, explicit-override precedence, blank-value fallback, empty-model rejection, OpenRouter namespace validation, factory defense, and unchanged OpenAI behavior.

#### Scenario: Parameterized model default tests run
- Given: a parameterized test suite that clears all `WHISPER_*` environment variables and covers `openai`, `groq`, `together`, `deepinfra`, `openrouter`, `local`, `custom`, and an unknown provider string, calling `load_config(require_api_key=False)` so the model validator still runs without a real key
- When: `uv run pytest tests/unit/test_config.py` is executed
- Then: every provider resolves to its declared `default_model`, with `openai` asserted as `whisper-1` and `groq` as `whisper-large-v3`

#### Scenario: Override and validation tests run
- Given: unit tests covering explicit `WHISPER_MODEL`, blank/whitespace values, an un-namespaced OpenRouter override, a namespaced OpenRouter override, an empty effective model routed through both a direct `validate_model()` call and the `WhisperConfig` validator with an empty table entry, and a `WhisperConfig.model_construct(provider="openrouter", model="")` config passed to `create_transcriber()`
- When: the test suite is executed
- Then: explicit values win, blank values fall back, and the un-namespaced OpenRouter case raises a `ValueError` with an actionable message
- And: the direct and validator paths both produce the empty-model `ValueError` naming the provider and the remediation
- And: the `model_construct()` factory case receives the provider default at the provider call while `config.model` remains unchanged

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
