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
