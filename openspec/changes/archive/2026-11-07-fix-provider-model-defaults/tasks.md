# Tasks

## 1. Provider model defaults (`src/whisper_dictate/config.py`)

- [x] 1.1 Add a `default_model` key to every entry in `PROVIDER_DEFAULTS` (`config.py:31-60`)
  - [x] 1.1.1 `openai → "whisper-1"` (unchanged behavior)
  - [x] 1.1.2 `groq → "whisper-large-v3"` (matches `.env.example:45`; note the README quick-start example `:77` and provider row `:469` use `whisper-large-v3-turbo`, so verify against Groq's catalog in task 7.7)
  - [x] 1.1.3 `openrouter → "microsoft/mai-transcribe-2"` (namespaced id valid for OpenRouter)
  - [x] 1.1.4 `together`, `deepinfra`, `local`, `custom → "whisper-1"` pending catalog verification (preserves current behavior)
- [x] 1.2 Tighten/narrow the table's type annotation from `dict[WhisperProvider, dict[str, str | None]]` to a `ProviderDefaults` `TypedDict` (`base_url: str | None`, `env_var: str | None`, `default_model: str`) and annotate the table `dict[WhisperProvider, ProviderDefaults]`; document each key's meaning in the comment above `PROVIDER_DEFAULTS`
- [x] 1.3 Add `resolve_model(provider: str, explicit_model: str) -> str` near `_resolve_provider_enum()` (`config.py:364-373`): resolve unknown providers to `CUSTOM`, strip the explicit value, return it when non-empty, otherwise return `PROVIDER_DEFAULTS[provider_enum]["default_model"]` (a `KeyError` there is a programming error). Both parameters are plain `str` (`WhisperProvider` is a `StrEnum`, a `str` subclass); `explicit_model` is never `None` inside the resolver — the only `None` comes from `os.getenv("WHISPER_MODEL")` and is collapsed by `or ""` in the env loader. Provider values stay case-sensitive and unstripped (normalizing them is out of scope)

## 2. Model resolution and validation (`src/whisper_dictate/config.py`)

- [x] 2.1 Change `WhisperConfig.model` from `default="whisper-1"` to `default=""` (`config.py:267-270`) while keeping the field type `str` (not `str | None`), and update its description to state that empty means "use provider default"
- [x] 2.2 Import `model_validator` from `pydantic` and add a `@model_validator(mode="after")` that assigns the resolved value and returns `self`, with a comment explaining why the resolution is stored rather than exposed as a computed property (transcript history logs `model_used`) and why `return self` is required:

  ```python
  @model_validator(mode="after")
  def _resolve_model(self) -> "WhisperConfig":
      self.model = resolve_model(self.provider, self.model)
      validate_model(self.provider, self.model)
      return self
  ```

- [x] 2.3 Add `validate_model(provider: str, model: str) -> None` that raises `ValueError` when the provider is `openrouter` and the effective model has no `/`; the message must name the invalid model and include `microsoft/mai-transcribe-2` and `openai/whisper-1` as valid examples
- [x] 2.4 Ensure `validate_model()` rejects an empty effective model for any provider with an actionable message that names the provider and tells the user to set `WHISPER_MODEL` or rely on the provider default (defense against bypassed defaults)
- [x] 2.5 Call `validate_model()` from the same model validator so both `load_config()` and direct `WhisperConfig(...)` construction validate identically
- [x] 2.6 Confirm non-OpenRouter providers are never namespace-validated (no slash requirement for `groq`, `together`, `deepinfra`, `local`, `custom`)

## 3. Environment loading (`src/whisper_dictate/config.py`)

- [x] 3.1 Replace `model=os.getenv("WHISPER_MODEL", "whisper-1")` with `model=os.getenv("WHISPER_MODEL") or ""` (`config.py:325`)
- [x] 3.2 Update the `_load_whisper_config_from_env()` docstring entry for `WHISPER_MODEL` from `Default: "whisper-1"` to "Default: empty → provider default" (`config.py:309`)
- [x] 3.3 Verify a copied `.env` containing `WHISPER_MODEL=` does not produce an empty or whitespace model after resolution

## 4. Factory defense (`src/whisper_dictate/transcription.py`)

- [x] 4.1 Import `resolve_model` from `whisper_dictate.config` inside `create_transcriber()` (`transcription.py:111-112`, alongside `PROVIDER_DEFAULTS`/`WhisperProvider`) and pass `model=resolve_model(config.provider, config.model)` when constructing `OpenAICompatibleProvider` (`transcription.py:138`)
- [x] 4.2 Confirm `create_transcriber()` still resolves `base_url` and `api_key` exactly as before and that the change is idempotent for already-validated configs
- [x] 4.3 Confirm the factory does not mutate `config.model`; the `model_construct()` bypass limitation (validators skipped, history may record the unresolved value) is documented in `design.md` rather than silently patched

## 5. Documentation

- [x] 5.1 `.env.example:10` (the uncommented `WHISPER_MODEL` line): change `WHISPER_MODEL=whisper-1` to `WHISPER_MODEL=` with a comment that blank means "use the provider default"
- [x] 5.2 `.env.example`: add a short default-model table/comment covering `openai`, `groq`, and `openrouter`; keep the Groq example (`:45`) and OpenRouter example's explicit `microsoft/mai-transcribe-2`
- [x] 5.3 `README.md` `WHISPER_MODEL` settings row (`:458`): default is provider-specific; blank means provider default
- [x] 5.4 `README.md` provider table rows (`:468-476`): list each provider's default model, change the OpenRouter row from "you must set `WHISPER_MODEL`" to "defaults to `microsoft/mai-transcribe-2`; overrides must be namespaced `vendor/model`", and reconcile the Groq row with the `whisper-large-v3-turbo` quick-start example (`:77`) and the `.env.example:45` default
- [x] 5.5 `README.md` quick-start OpenRouter example (`~86-88`): note that `WHISPER_MODEL` is optional now that a valid default exists

## 6. Regression tests (`tests/unit/test_config.py`)

- [x] 6.1 Extend `test_provider_defaults_structure` (`:55-59`) to assert every provider entry has a non-empty string `default_model`; extend `test_provider_defaults_keys` (`:50-53`) for the new key coverage and `test_openrouter_defaults` (`:79-83`) for the OpenRouter default model
- [x] 6.2 Keep `TestWhisperConfig.test_defaults` (`~184`) and `TestLoadWhisperConfigFromEnv.test_defaults_no_env` (`:228-239`) asserting `whisper-1` for the default OpenAI provider (unchanged behavior)
- [x] 6.3 Add parameterized tests over all providers asserting `load_config(require_api_key=False).openai.model` equals each provider's `default_model` — `require_api_key=False` skips only the API-key check while the model validator still runs, so no real key is needed — with `openrouter` asserted as `microsoft/mai-transcribe-2`, `groq` as `whisper-large-v3`, and `openai` as `whisper-1`
- [x] 6.4 Add a test that `WhisperConfig(provider="openrouter")` resolves the OpenRouter default without reading the environment
- [x] 6.5 Add a test that an explicit `WHISPER_MODEL` wins over the provider default, including leading/trailing whitespace trimming
- [x] 6.6 Add tests that absent, empty, and whitespace-only `WHISPER_MODEL` values all fall back to the provider default
- [x] 6.7 Add a test that `WHISPER_PROVIDER=openrouter` + `WHISPER_MODEL=whisper-1` raises `ValueError` mentioning the invalid model and a valid namespaced example
- [x] 6.8 Add a test that a namespaced OpenRouter model is accepted and that `groq`/`custom` models without `/` are not rejected
- [x] 6.9 Add a test for an unknown provider string resolving to the `custom` default model
- [x] 6.10 Add a test that an empty effective model raises `ValueError` with an actionable message for every provider (direct `validate_model()` call and the validator path)
- [x] 6.11 Assert the resolved model reaches both consumers: `config.openai.model` (through the `AppConfig.openai` `default_factory` chain) and the history writer, which records `model_used`/`openai_model` from that field — a dictation test with `WHISPER_PROVIDER=openrouter` and no `WHISPER_MODEL` must store `model_used == "microsoft/mai-transcribe-2"`
- [x] 6.12 Add a factory test that a `WhisperConfig.model_construct(provider="openrouter", model="")` config is resolved to `microsoft/mai-transcribe-2` for the provider call, and that the already-resolved config passes through unchanged

## 7. Quality gates

- [x] 7.1 Run `uv run pytest` — full suite passes
- [x] 7.2 Run `uv run mypy` — the full strict gate stays clean for the whole package, not just `config.py` and `transcription.py` (no new per-module opt-outs)
- [x] 7.3 Run `uv run ruff check .` and `uv run ruff format --check .` — clean
- [x] 7.4 Run the coverage floors (`uv run python scripts/check_coverage.py`) — per-module floors hold and the new resolver/validator/factory branches are covered
- [x] 7.5 Manual smoke test: `WHISPER_PROVIDER=openrouter OPENROUTER_API_KEY=dummy whisper-dictate info` shows the resolved OpenRouter model; setting `WHISPER_MODEL=whisper-1` produces the actionable configuration error
- [x] 7.6 Run `openspec validate fix-provider-model-defaults` and `openspec validate --specs` — valid
- [x] 7.7 File a follow-up to verify canonical model ids for `together`, `deepinfra`, `local`, and `custom` against each provider's catalog (and confirm `groq`'s `whisper-large-v3` vs the README's `whisper-large-v3-turbo`) — filed as https://github.com/seszele64/dictator/issues/33
