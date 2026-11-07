# Design: Fix provider model defaults

## Technical Approach

Model resolution becomes provider-aware in the configuration layer, so every consumer sees a concrete model instead of the hard-coded `whisper-1`.

1. **Provider table** (`src/whisper_dictate/config.py:31-60`): add a `default_model` key to every `PROVIDER_DEFAULTS` entry. The table is typed with a `TypedDict` so the model key is guaranteed while the other two stay nullable:

   ```python
   class ProviderDefaults(TypedDict):
       base_url: str | None
       env_var: str | None
       default_model: str

   PROVIDER_DEFAULTS: dict[WhisperProvider, ProviderDefaults] = {...}
   ```

   Verified values: `openai → whisper-1`, `groq → whisper-large-v3`, `openrouter → microsoft/mai-transcribe-2`. The Groq value matches the `# WHISPER_MODEL=whisper-large-v3` line at `.env.example:45`; the README quick-start Groq example (`README.md:77`) and provider row (`README.md:469`) instead use `whisper-large-v3-turbo`, so the Groq id is pinned to `.env.example` and verified against Groq's catalog in task 7.7. Providers whose canonical id is not verified in this change (`together`, `deepinfra`, `local`, `custom`) keep `whisper-1`, which is today's effective behavior, so no user regresses. Unknown provider strings resolve to `custom` through the existing `_resolve_provider_enum()` helper.
2. **Single resolver** (`config.py`, beside `_resolve_provider_enum()`): add `resolve_model(provider: str, explicit_model: str) -> str`, which resolves the enum (unknown → `CUSTOM`), strips the explicit value, returns it when non-empty, and otherwise returns `PROVIDER_DEFAULTS[provider_enum]["default_model"]` (a `KeyError` there means the table is incomplete — a programming error, never user input). Both parameters are plain `str`; `WhisperProvider` is a `StrEnum`, so enum members are valid `str` arguments. `explicit_model` is never `None` inside the resolver: the only `None` originates from `os.getenv("WHISPER_MODEL")` and is collapsed by `or ""` in the env loader, and the field default is `""`. Provider values themselves stay case-sensitive and unstripped (out of scope).
3. **Model field** (`config.py:267-270`): change `model` from `default="whisper-1"` to `default=""` — the empty string is the "not configured" sentinel — and keep the field type `str` (not `str | None`). Add a `@model_validator(mode="after")` that resolves and validates in place:

   ```python
   @model_validator(mode="after")
   def _resolve_model(self) -> "WhisperConfig":
       self.model = resolve_model(self.provider, self.model)
       validate_model(self.provider, self.model)
       return self
   ```

   `return self` is required: a `mode="after"` model validator must return the instance, and returning `None` would be a validation error. Because the validator lives on the model, both real entry points — `WhisperConfig(...)` and `_load_whisper_config_from_env()` — resolve identically.
4. **Environment loading** (`config.py:325`): read `model=os.getenv("WHISPER_MODEL") or ""` so an unset *or empty* variable reaches the resolver as "not configured". `os.getenv("WHISPER_MODEL", "whisper-1")` is removed; it is the direct cause of the bug. This `or ""` is the only place a `None` can appear, and it never reaches `resolve_model()`.
5. **Validation** (`config.py`): `validate_model(provider, model)` raises `ValueError` when the effective model is empty for any provider, and when the provider is `openrouter` and the effective model contains no `/`. Each message names the provider/invalid model, says to set `WHISPER_MODEL` or rely on the provider default, and the OpenRouter case lists `microsoft/mai-transcribe-2` and `openai/whisper-1`. No other provider is namespace-validated. The validator raises during `load_config()`, before any HTTP request.
6. **Factory defense** (`transcription.py:138`): import `resolve_model` from `whisper_dictate.config` inside `create_transcriber()` (same local import block as `PROVIDER_DEFAULTS`/`WhisperProvider`, `transcription.py:111-112`) and pass `model=resolve_model(config.provider, config.model)` to `OpenAICompatibleProvider`. This is idempotent for validated configs and covers the provider call for callers/tests that build configs with `model_construct()` or mutate `model` after validation. It does **not** repair `config.model` itself: Pydantic v2 skips validators entirely in `model_construct()`, so direct readers — transcript history records `config.openai.model` verbatim (`dictation.py:224`, `:264`, `:428`, `:445`, `:552`) — may still see an unresolved value for such bypassed configs. Production entry points (`bootstrap()` → `load_config()`) always validate; the divergence is a documented limitation, covered by task 6.11.
7. **Docs**: `.env.example:10` becomes `WHISPER_MODEL=` with a comment that blank means "use the provider default"; the OpenRouter block keeps its explicit example. `README.md:458` documents the per-provider default for `WHISPER_MODEL`, and the provider table rows (`README.md:468-476`) show each provider's default rather than claiming `whisper-1` universally and telling OpenRouter users they must always set `WHISPER_MODEL`.

## Architecture Decisions

### Decision: Store `default_model` in `PROVIDER_DEFAULTS` rather than a per-provider class or an if/elif chain
- **Pros**: Provider facts (base URL, key env var, model) stay in one table; adding a provider forces a decision about all three; tests can assert table completeness generically.
- **Cons**: The value type must be tightened/narrowed from the current `dict[str, str | None]`, which cannot express "model is always a string" while the other keys are nullable. Use a `ProviderDefaults` `TypedDict` (`base_url: str | None`, `env_var: str | None`, `default_model: str`) and annotate the table `dict[WhisperProvider, ProviderDefaults]`.

### Decision: Resolve inside a `WhisperConfig` model validator instead of only in the env loader
- **Pros**: Covers both entry points (`load_config()` and direct `WhisperConfig(...)` used by tests and provider contracts); guarantees `config.model` and the `model_used` field written to transcript history are truthful; keeps `create_transcriber()` simple.
- **Cons**: Construction now performs provider logic and can raise `ValueError`; mutating `self` in a `mode="after"` validator is slightly unusual in Pydantic v2 and needs a comment explaining why a computed field is not used (the resolved value must persist, not be recomputed) and why the validator must `return self`.

### Decision: Use `""` as the "not configured" sentinel for `WhisperConfig.model`
- **Pros**: Makes the field non-optional for consumers (no `None` checks in `OpenAICompatibleProvider`); maps naturally onto "`WHISPER_MODEL` absent or empty"; distinguishable from a real model string before resolution.
- **Cons**: An unresolved empty model can still leak if someone bypasses validators — Pydantic `model_construct()` skips validators entirely. The factory resolve in `create_transcriber()` covers the provider call only; transcript history reads `config.openai.model` directly and may therefore diverge (record an unresolved value) for such callers. This is a documented limitation, not silently defended: production entry points always validate, `validate_model()` rejects an empty effective model on every validated path, and task 6.11 pins the history behavior for the validated case.

### Decision: Treat blank/whitespace `WHISPER_MODEL` as unset
- **Pros**: A copied `.env.example` with `WHISPER_MODEL=` (the new default line) works out of the box; whitespace from shell or dotenv quoting does not produce a bogus model id.
- **Cons**: A user cannot intentionally send an empty model string — not a meaningful request for any supported provider.

### Decision: Reject un-namespaced OpenRouter models at configuration load
- **Pros**: Converts an opaque provider 400/404 into a local, actionable error that names the model and shows valid examples; catches the exact regression this change exists to prevent.
- **Cons**: Hard-codes OpenRouter's id convention. If OpenRouter ever exposes an alias without `/`, the check must be relaxed; therefore the check is limited to `openrouter` and implemented as one small predicate with a test. An empty effective model is rejected for every provider, which is a separate guard against bypassed defaults rather than a namespace rule.

### Decision: Keep `whisper-1` for providers whose canonical id is unverified
- **Pros**: Zero behavior change outside OpenRouter; avoids swapping one invalid default for another (e.g. guessing a Together or DeepInfra id); the change stays reviewable and reversible.
- **Cons**: `together`/`deepinfra` users still need `WHISPER_MODEL` for a provider-specific model; documented as a follow-up to verify ids against each provider's catalog rather than guessed now.

## Data Flow

```text
CLI / toggle ──> bootstrap()                         (app.py)
                  load_dotenv()  (mutates os.environ)
                              │
                              ▼
                  load_config(require_api_key=...)
                              │
                              ▼
                  AppConfig()                         (config.py:334)
                    openai: default_factory=
                      _load_whisper_config_from_env
                              │
WHISPER_PROVIDER ─────────────┤
WHISPER_MODEL (may be         │
  absent or empty) ───────────┘
                              ▼
        model = os.getenv("WHISPER_MODEL") or ""
                              │
                              ▼
        WhisperConfig(provider=..., model="")
                              │
                    model_validator(mode="after")
                              │
        ┌─────────────────────┴───────────────────────┐
        │ resolve_model(provider, model)              │
        │  explicit non-empty ── wins                 │
        │  else PROVIDER_DEFAULTS[provider_enum]      │
        │        ["default_model"]                    │
        └─────────────────────┬───────────────────────┘
                              │
                    validate_model(provider, model)
                    (empty ⇒ ValueError, any provider;
                     openrouter ⇒ requires "/")
                              │
                              ▼
                    AppConfig.openai.model
                     │                      │
                     ▼                      ▼
          create_transcriber()      dictation history
          resolve_model() again     model_used / openai_model
                     │
                     ▼
        OpenAICompatibleProvider(model=...)
                     │
                     ▼
        audio.transcriptions.create(model=...)
```

`WhisperConfig` constructed directly (tests, contract tests, future callers) follows the same validator path with the same defaults and validation, minus the environment read. `model_construct()` skips that path entirely; the factory resolve covers the provider call, while history may diverge — see the decision above.

## File Changes

- `src/whisper_dictate/config.py`
  - Add `default_model` to all seven `PROVIDER_DEFAULTS` entries (`config.py:31-60`); OpenRouter gets `microsoft/mai-transcribe-2`, Groq `whisper-large-v3`, OpenAI stays `whisper-1`. Annotate the table with `ProviderDefaults` (`TypedDict`).
  - Add `resolve_model()` and `validate_model()` helpers near `_resolve_provider_enum()` (`config.py:364-373`).
  - Change `WhisperConfig.model` default to `""` and add the `model_validator` (`config.py:267-270`); import `model_validator` from `pydantic`.
  - Change env loading to `model=os.getenv("WHISPER_MODEL") or ""` and update the docstring line that promises `Default: "whisper-1"` (`config.py:309`, `config.py:325`).
- `src/whisper_dictate/transcription.py`
  - Import `resolve_model` alongside `PROVIDER_DEFAULTS`/`WhisperProvider` and resolve the model defensively when constructing `OpenAICompatibleProvider` (`transcription.py:111-112`, `transcription.py:138`).
- `.env.example`
  - Line 10: `WHISPER_MODEL=` plus a comment that blank means provider default; add a one-line default table for the common providers.
- `README.md`
  - `WHISPER_MODEL` row (`:458`): default is per-provider, blank = provider default.
  - Provider table rows (`:468-476`): show each provider's default model; the OpenRouter row states the `microsoft/mai-transcribe-2` default and the `vendor/model` requirement, and the Groq row reconciles `whisper-large-v3` with the `whisper-large-v3-turbo` quick-start example (`:77`).
- `tests/unit/test_config.py`
  - `test_provider_defaults_keys` (`:50-53`) and `test_provider_defaults_structure` (`:55-59`) additionally assert `default_model` is present and non-empty; `test_openrouter_defaults` (`:79-83`) asserts the OpenRouter default model.
  - `TestWhisperConfig.test_defaults` (`~184`) and `TestLoadWhisperConfigFromEnv.test_defaults_no_env` (`:228-239`) assert `whisper-1` for the default OpenAI provider (unchanged).
  - New parameterized tests: per-provider defaults (called through `load_config(require_api_key=False)` so the model validator runs without a key), explicit override, blank/whitespace fallback, empty-model rejection, OpenRouter namespace rejection/acceptance, non-OpenRouter exemption, factory resolution for `model_construct()` configs, and the resolved model recorded in history.

## Risks / Mitigations

- **Risk**: Raising on un-namespaced OpenRouter models breaks an existing `.env` that sets `WHISPER_MODEL=whisper-1` with `WHISPER_PROVIDER=openrouter`.
  **Mitigation**: That combination could never transcribe successfully; the new error names the fix. Document the migration in the error message and README.
- **Risk**: Changing the `WhisperConfig.model` field default from `"whisper-1"` to `""` may surprise code that reads the raw field before validation.
  **Mitigation**: Validators always populate it; `create_transcriber()` resolves defensively; existing tests asserting `whisper-1` for OpenAI still pass.
- **Risk**: A guessed default for `groq` (`whisper-large-v3`) could be wrong.
  **Mitigation**: `.env.example:45` documents `whisper-large-v3` for Groq, but the README quick-start (`:77`) and provider row (`:469`) use `whisper-large-v3-turbo`; the id is pinned to `.env.example` and task 7.7 verifies it against Groq's catalog. Only Groq and OpenRouter get non-`whisper-1` values; the remaining entries stay `whisper-1` until verified.
- **Risk**: `model_construct()` configurations bypass the validator, so `config.openai.model` can stay empty even though the provider received a resolved model, and transcript history would record the unresolved value.
  **Mitigation**: Documented limitation (see the sentinel decision); the factory resolve keeps the provider call correct, production paths always validate, and task 6.11 pins the history behavior for validated configs.
- **Risk**: Pydantic `mode="after"` validator mutation interacts badly with a future `model_config = frozen`.
  **Mitigation**: Use a computed property only if the model is ever frozen; today `WhisperConfig` is mutable and the resolved value must be stored for history logging.
