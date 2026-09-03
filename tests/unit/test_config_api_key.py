"""Regression tests for load_config() provider and API-key handling.

Covers the fix-provider-crash change:
- Keyless providers (local, custom) and unknown provider strings (which fall
  back to CUSTOM) must load WITHOUT an API key — previously load_config()
  crashed with an error (env_var=None passed to os.getenv) and then rejected
  keyless providers outright.
- Auth-requiring providers (openai, groq, together, deepinfra) must still
  raise ValueError when no key is available.
- load_config(require_api_key=False) and validate_api_key() support lazy
  validation for non-transcription CLI commands.
"""

import pytest

from whisper_dictate.config import load_config, validate_api_key

# Providers that declare an auth env var in PROVIDER_DEFAULTS
AUTH_PROVIDERS = ["openai", "groq", "together", "deepinfra"]
# Providers that are keyless by design (env_var=None), plus an unknown string
# that resolves to CUSTOM
KEYLESS_PROVIDERS = ["local", "custom", "definitely-not-a-provider"]

ALL_KEY_ENV_VARS = [
    "WHISPER_API_KEY",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
    "DEEPINFRA_API_KEY",
]


@pytest.fixture
def clean_provider_env(monkeypatch):
    """Remove all provider/API-key env vars so tests fully control the config.

    Note: tests/conftest.py sets OPENAI_API_KEY at session scope; delenv
    undoes that for these tests and monkeypatch restores it afterwards.
    """
    for var in (
        "WHISPER_PROVIDER",
        "WHISPER_API_KEY",
        "WHISPER_BASE_URL",
        "WHISPER_MODEL",
        "WHISPER_TIMEOUT",
        "WHISPER_LANGUAGE",
        "WHISPER_TEMPERATURE",
        "WHISPER_TASK",
        "WHISPER_SILENCE_THRESHOLD_DBFS",
        *ALL_KEY_ENV_VARS,
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


class TestLoadConfigProviders:
    """Parameterized load_config() tests per provider, with and without keys."""

    @pytest.mark.parametrize("provider", AUTH_PROVIDERS)
    def test_auth_provider_without_key_raises(self, clean_provider_env, provider):
        """openai/groq/together/deepinfra without any key must raise ValueError."""
        clean_provider_env.setenv("WHISPER_PROVIDER", provider)
        with pytest.raises(ValueError, match="API key not found"):
            load_config()

    @pytest.mark.parametrize("provider", KEYLESS_PROVIDERS)
    def test_keyless_provider_loads_without_key(self, clean_provider_env, provider):
        """local/custom (and unknown → CUSTOM) must load with NO key configured.

        Regression: this previously crashed with an unhandled error because
        os.getenv() was called with the provider's None env var.
        """
        clean_provider_env.setenv("WHISPER_PROVIDER", provider)
        config = load_config()
        assert config.openai.provider == provider
        assert config.openai.api_key == ""

    @pytest.mark.parametrize("provider", AUTH_PROVIDERS + KEYLESS_PROVIDERS)
    def test_explicit_key_loads_for_all_providers(self, clean_provider_env, provider):
        """An explicitly configured WHISPER_API_KEY always loads."""
        clean_provider_env.setenv("WHISPER_PROVIDER", provider)
        clean_provider_env.setenv("WHISPER_API_KEY", "explicit-key")
        config = load_config()
        assert config.openai.api_key == "explicit-key"

    @pytest.mark.parametrize(
        ("provider", "env_var"),
        [
            ("openai", "OPENAI_API_KEY"),
            ("groq", "GROQ_API_KEY"),
            ("together", "TOGETHER_API_KEY"),
            ("deepinfra", "DEEPINFRA_API_KEY"),
        ],
    )
    def test_provider_env_var_fallback(self, clean_provider_env, provider, env_var):
        """Auth providers resolve their key from the provider-specific env var."""
        clean_provider_env.setenv("WHISPER_PROVIDER", provider)
        clean_provider_env.setenv(env_var, "fallback-key")
        # Must not raise: the key is found via the provider's env var
        load_config()

    def test_invalid_provider_falls_back_to_keyless_custom(self, clean_provider_env):
        """An unrecognized provider string is treated as keyless CUSTOM."""
        clean_provider_env.setenv("WHISPER_PROVIDER", "not-a-real-provider")
        # Must not raise (unknown providers are keyless by design)
        config = load_config()
        # The raw provider string is preserved in the config
        assert config.openai.provider == "not-a-real-provider"

    def test_require_api_key_false_skips_validation(self, clean_provider_env):
        """require_api_key=False must skip validation for auth providers too."""
        clean_provider_env.setenv("WHISPER_PROVIDER", "openai")
        # With the default, validation fails...
        with pytest.raises(ValueError, match="API key not found"):
            load_config()
        # ...but lazily loading config must succeed
        config = load_config(require_api_key=False)
        assert config.openai.provider == "openai"


class TestValidateApiKey:
    """Direct tests for validate_api_key(), used by the CLI's dictate command."""

    def test_keyless_local_passes(self, clean_provider_env):
        clean_provider_env.setenv("WHISPER_PROVIDER", "local")
        config = load_config(require_api_key=False)
        validate_api_key(config)  # must not raise

    def test_unknown_provider_passes(self, clean_provider_env):
        clean_provider_env.setenv("WHISPER_PROVIDER", "bogus")
        config = load_config(require_api_key=False)
        validate_api_key(config)  # must not raise

    def test_auth_provider_without_key_raises(self, clean_provider_env):
        clean_provider_env.setenv("WHISPER_PROVIDER", "openai")
        config = load_config(require_api_key=False)
        with pytest.raises(ValueError, match="API key not found"):
            validate_api_key(config)

    @pytest.mark.parametrize(
        "provider,env_var",
        [
            ("openai", "OPENAI_API_KEY"),
            ("groq", "GROQ_API_KEY"),
            ("together", "TOGETHER_API_KEY"),
            ("deepinfra", "DEEPINFRA_API_KEY"),
        ],
    )
    def test_auth_provider_with_env_key_passes(self, clean_provider_env, provider, env_var):
        clean_provider_env.setenv("WHISPER_PROVIDER", provider)
        clean_provider_env.setenv(env_var, "env-key")
        config = load_config(require_api_key=False)
        validate_api_key(config)  # must not raise
