# Proposal: Fix provider model defaults

## Intent
`WHISPER_MODEL` defaults to `whisper-1` in `config.py` and `.env.example`, but `whisper-1` is not a valid OpenRouter model identifier — OpenRouter requires namespaced ids such as `microsoft/mai-transcribe-2` or `openai/whisper-1`. An OpenRouter user who configures only `WHISPER_PROVIDER` and `OPENROUTER_API_KEY` therefore gets an opaque provider-side 400/404 at transcription time, with nothing in the configuration layer pointing at the model as the cause. `PROVIDER_DEFAULTS` already carries each provider's `base_url` and key env var but no model, so the model default cannot follow the provider. This change gives every provider a default model, makes a non-empty `WHISPER_MODEL` override it, and validates effective OpenRouter models so misconfiguration fails fast with an actionable message.

## Scope
**In scope:**
- Add a `default_model` key to every `PROVIDER_DEFAULTS` entry in `src/whisper_dictate/config.py`
- Set the OpenRouter default to a valid namespaced transcription model (`microsoft/mai-transcribe-2`)
- Keep OpenAI behavior unchanged (`whisper-1`) and preserve current defaults for providers whose canonical id is not verified in this change
- Resolution rule: a non-empty `WHISPER_MODEL` wins; an unset, empty, or whitespace-only value falls back to the selected provider's default
- Apply the same resolution to both entry points — environment loading (`_load_whisper_config_from_env()`) and direct `WhisperConfig(...)` construction — so consumers never see an unresolved model
- Validate effective OpenRouter models that lack a `vendor/model` namespace, raising a `ValueError` that names the offending model and the expected shape
- Reject an empty effective model for any provider with an actionable `ValueError` (defense against bypassed defaults)
- Update `.env.example` (blank `WHISPER_MODEL` means "use provider default", with comments) and the README provider/settings tables
- Regression tests in `tests/unit/test_config.py` for per-provider defaults (including Groq), override precedence, blank handling, empty-model rejection, OpenRouter validation, factory defense, and unchanged OpenAI behavior

**Out of scope:**
- Adding or removing providers, or changing provider enum values
- Querying a provider's `/models` endpoint at runtime or otherwise discovering model ids dynamically
- Automatic model fallback chains or retry-with-another-model behavior
- Validating model ids for providers other than OpenRouter (there is no stable public grammar for groq/together/deepinfra/local/custom ids)
- Changes to `OpenAICompatibleProvider` request shape, audio handling, or dictation flow
- Changing the existing API-key resolution/validation behavior
- Normalizing provider values: they stay case-sensitive and unstripped, exactly as today (`WhisperProvider("Groq")` still falls back to `custom`)

## Approach
Extend `PROVIDER_DEFAULTS` with `default_model` so provider-specific knowledge stays in one table (typed as `ProviderDefaults`, a `TypedDict` that keeps `base_url`/`env_var` nullable while `default_model` is always a `str`), then introduce a single `resolve_model(provider: str, explicit_model: str) -> str` helper that trims the explicit value and falls back to the provider default. Both parameters are plain `str` (`WhisperProvider` is a `StrEnum`, so enum members are valid `str` arguments); `explicit_model` is never `None` inside the resolver, because the only `None` comes from `os.getenv("WHISPER_MODEL")` and is collapsed to `""` by `or ""` in the env loader, and the field default is `""`. Apply that helper inside a `WhisperConfig` `model_validator(mode="after")` instead of only in the env loader, because both `_load_whisper_config_from_env()` and direct `WhisperConfig(...)` construction are real entry points (tests and contract tests construct the model directly). The `model` field default becomes empty to signal "unset", `WHISPER_MODEL` is read with an empty fallback, and validation for OpenRouter's namespaced ids lives beside the resolver so an explicit `whisper-1` override fails at configuration load with a message that shows valid examples. `create_transcriber()` keeps consuming `config.model` and gains a defensive `resolve_model()` for callers that bypass validation — Pydantic `model_construct()` skips validators entirely, so the factory resolve protects the provider call but direct readers (for example transcript history) can still see an unresolved value; that limitation is documented in `design.md`. Documentation and tests are updated last, with OpenAI asserted byte-for-byte unchanged.
