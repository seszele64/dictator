"""Unit tests for the whisper_dictate configuration module."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from whisper_dictate.config import (
    PROVIDER_DEFAULTS,
    AppConfig,
    AudioConfig,
    DatabaseConfig,
    OpenAIConfig,
    WhisperConfig,
    WhisperProvider,
    _load_whisper_config_from_env,
    load_config,
    resolve_model,
    validate_model,
)


class TestWhisperProvider:
    """Tests for the WhisperProvider enum."""

    def test_provider_values(self):
        """All 7 enum members have correct string values."""
        assert WhisperProvider.OPENAI == "openai"
        assert WhisperProvider.GROQ == "groq"
        assert WhisperProvider.TOGETHER == "together"
        assert WhisperProvider.DEEPINFRA == "deepinfra"
        assert WhisperProvider.OPENROUTER == "openrouter"
        assert WhisperProvider.LOCAL == "local"
        assert WhisperProvider.CUSTOM == "custom"

    def test_provider_string_equality(self):
        """StrEnum members compare equal to their string values."""
        assert WhisperProvider.OPENAI == "openai"

    def test_provider_from_string(self):
        """Providers can be constructed from their string values."""
        assert WhisperProvider("groq") == WhisperProvider.GROQ

    def test_provider_invalid_string_raises(self):
        """Unknown provider strings raise ValueError."""
        with pytest.raises(ValueError):
            WhisperProvider("unknown")

    def test_provider_defaults_keys(self):
        """PROVIDER_DEFAULTS has exactly the 7 providers as keys."""
        assert set(PROVIDER_DEFAULTS) == set(WhisperProvider)
        assert len(PROVIDER_DEFAULTS) == 7
        for defaults in PROVIDER_DEFAULTS.values():
            assert set(defaults) == {"base_url", "env_var", "default_model"}

    def test_provider_defaults_structure(self):
        """Each provider default has base_url, env_var and a non-empty model."""
        for defaults in PROVIDER_DEFAULTS.values():
            assert "base_url" in defaults
            assert "env_var" in defaults
            assert "default_model" in defaults
            assert isinstance(defaults["default_model"], str)
            assert defaults["default_model"].strip() != ""

    def test_openai_defaults(self):
        """OpenAI uses the SDK default base_url and OPENAI_API_KEY."""
        defaults = PROVIDER_DEFAULTS[WhisperProvider.OPENAI]
        assert defaults["base_url"] is None
        assert defaults["env_var"] == "OPENAI_API_KEY"

    def test_groq_defaults(self):
        """Groq uses its OpenAI-compatible endpoint and GROQ_API_KEY."""
        defaults = PROVIDER_DEFAULTS[WhisperProvider.GROQ]
        assert defaults["base_url"] == "https://api.groq.com/openai/v1"
        assert defaults["env_var"] == "GROQ_API_KEY"

    def test_local_defaults(self):
        """Local servers use localhost and require no API key."""
        defaults = PROVIDER_DEFAULTS[WhisperProvider.LOCAL]
        assert defaults["base_url"] == "http://localhost:8000/v1"
        assert defaults["env_var"] is None

    def test_openrouter_defaults(self):
        """OpenRouter uses its OpenAI-compatible endpoint and OPENROUTER_API_KEY."""
        defaults = PROVIDER_DEFAULTS[WhisperProvider.OPENROUTER]
        assert defaults["base_url"] == "https://openrouter.ai/api/v1"
        assert defaults["env_var"] == "OPENROUTER_API_KEY"
        assert defaults["default_model"] == "microsoft/mai-transcribe-2"

    def test_custom_defaults(self):
        """Custom providers require explicit configuration."""
        defaults = PROVIDER_DEFAULTS[WhisperProvider.CUSTOM]
        assert defaults["base_url"] is None
        assert defaults["env_var"] is None


class TestDatabaseConfig:
    """Tests for the DatabaseConfig model."""

    def test_defaults(self):
        """DatabaseConfig uses XDG-style defaults."""
        config = DatabaseConfig()
        assert config.path is None
        assert config.recordings_path is None
        assert config.log_retention_days == 30
        assert config.min_free_space_mb == 100

    def test_custom_values(self):
        """Custom values are stored on the model."""
        config = DatabaseConfig(
            path=Path("/tmp/custom.db"),
            recordings_path=Path("/tmp/custom-recordings"),
            log_retention_days=60,
            min_free_space_mb=500,
        )
        assert config.path == Path("/tmp/custom.db")
        assert config.recordings_path == Path("/tmp/custom-recordings")
        assert config.log_retention_days == 60
        assert config.min_free_space_mb == 500

    def test_get_database_path_explicit(self):
        """Explicit path is returned as-is."""
        assert DatabaseConfig(path=Path("/tmp/test.db")).get_database_path() == Path("/tmp/test.db")

    def test_get_database_path_xdg(self, monkeypatch):
        """XDG_DATA_HOME is used for the database location."""
        monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg")
        assert DatabaseConfig().get_database_path() == Path("/tmp/xdg/whisper-dictate/whisper-dictate.db")

    def test_get_database_path_default(self, monkeypatch):
        """Without XDG_DATA_HOME, ~/.local/share is used."""
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        expected = Path.home() / ".local" / "share" / "whisper-dictate" / "whisper-dictate.db"
        assert DatabaseConfig().get_database_path() == expected

    def test_get_recordings_path_explicit(self):
        """Explicit recordings path is returned as-is."""
        assert DatabaseConfig(recordings_path=Path("/tmp/recordings")).get_recordings_path() == Path("/tmp/recordings")

    def test_get_recordings_path_xdg(self, monkeypatch):
        """XDG_DATA_HOME is used for the recordings location."""
        monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg")
        assert DatabaseConfig().get_recordings_path() == Path("/tmp/xdg/whisper-dictate/recordings")

    def test_get_recordings_path_default(self, monkeypatch):
        """Without XDG_DATA_HOME, ~/.local/share is used."""
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        expected = Path.home() / ".local" / "share" / "whisper-dictate" / "recordings"
        assert DatabaseConfig().get_recordings_path() == expected


class TestAudioConfig:
    """Tests for the AudioConfig model."""

    def test_defaults(self):
        """AudioConfig uses sensible recording defaults."""
        config = AudioConfig()
        assert config.sample_rate == 16000
        assert config.channels == 1
        assert config.duration == 5.0
        assert config.device is None
        assert config.mp3_enabled is True
        assert config.mp3_bitrate == "128k"
        assert config.keep_wav is False

    def test_custom_values(self):
        """Custom values are stored on the model."""
        config = AudioConfig(
            sample_rate=44100,
            channels=2,
            duration=10.0,
            device=3,
            mp3_enabled=False,
            mp3_bitrate="64k",
            keep_wav=True,
        )
        assert config.sample_rate == 44100
        assert config.channels == 2
        assert config.duration == 10.0
        assert config.device == 3
        assert config.mp3_enabled is False
        assert config.mp3_bitrate == "64k"
        assert config.keep_wav is True


class TestWhisperConfig:
    """Tests for the WhisperConfig model."""

    def test_defaults(self):
        """WhisperConfig uses OpenAI defaults."""
        config = WhisperConfig()
        assert config.provider == "openai"
        assert config.api_key == ""
        assert config.base_url is None
        assert config.model == "whisper-1"
        assert config.timeout == 30.0
        assert config.language is None
        assert config.temperature == 0.0
        assert config.silence_threshold_dbfs == -50.0
        assert config.task is None

    def test_custom_values(self):
        """Custom values are stored on the model."""
        config = WhisperConfig(
            provider="groq",
            api_key="secret",
            base_url="https://api.example.com",
            model="whisper-large-v3",
            timeout=60.0,
            language="de",
            temperature=0.5,
            silence_threshold_dbfs=-40.0,
            task="translate",
        )
        assert config.provider == "groq"
        assert config.api_key == "secret"
        assert config.base_url == "https://api.example.com"
        assert config.model == "whisper-large-v3"
        assert config.timeout == 60.0
        assert config.language == "de"
        assert config.temperature == 0.5
        assert config.silence_threshold_dbfs == -40.0
        assert config.task == "translate"

    def test_openai_config_alias(self):
        """OpenAIConfig is an alias for WhisperConfig."""
        assert OpenAIConfig is WhisperConfig


class TestLoadWhisperConfigFromEnv:
    """Tests for _load_whisper_config_from_env."""

    def test_defaults_no_env(self, env_isolator):
        """With no WHISPER_* env vars set, defaults are returned."""
        config = _load_whisper_config_from_env()
        assert config.provider == "openai"
        assert config.api_key == ""
        assert config.base_url is None
        assert config.model == "whisper-1"
        assert config.timeout == 30.0
        assert config.language is None
        assert config.temperature == 0.0
        assert config.silence_threshold_dbfs == -50.0
        assert config.task is None

    def test_provider_from_env(self, monkeypatch):
        """WHISPER_PROVIDER sets the provider."""
        monkeypatch.setenv("WHISPER_PROVIDER", "groq")
        assert _load_whisper_config_from_env().provider == "groq"

    def test_api_key_from_env(self, monkeypatch):
        """WHISPER_API_KEY sets the API key."""
        monkeypatch.setenv("WHISPER_API_KEY", "test-key")
        assert _load_whisper_config_from_env().api_key == "test-key"

    def test_base_url_from_env(self, monkeypatch):
        """WHISPER_BASE_URL sets the base URL."""
        monkeypatch.setenv("WHISPER_BASE_URL", "https://custom.api.com")
        assert _load_whisper_config_from_env().base_url == "https://custom.api.com"

    def test_model_from_env(self, monkeypatch):
        """WHISPER_MODEL sets the model."""
        monkeypatch.setenv("WHISPER_MODEL", "whisper-large-v3")
        assert _load_whisper_config_from_env().model == "whisper-large-v3"

    def test_timeout_from_env(self, monkeypatch):
        """WHISPER_TIMEOUT sets the timeout as a float."""
        monkeypatch.setenv("WHISPER_TIMEOUT", "60.0")
        assert _load_whisper_config_from_env().timeout == 60.0

    def test_language_from_env(self, monkeypatch):
        """WHISPER_LANGUAGE sets the language hint."""
        monkeypatch.setenv("WHISPER_LANGUAGE", "en")
        assert _load_whisper_config_from_env().language == "en"

    def test_temperature_from_env(self, monkeypatch):
        """WHISPER_TEMPERATURE sets the sampling temperature."""
        monkeypatch.setenv("WHISPER_TEMPERATURE", "0.5")
        assert _load_whisper_config_from_env().temperature == 0.5

    def test_silence_threshold_from_env(self, monkeypatch):
        """WHISPER_SILENCE_THRESHOLD_DBFS sets the silence threshold."""
        monkeypatch.setenv("WHISPER_SILENCE_THRESHOLD_DBFS", "-60.0")
        assert _load_whisper_config_from_env().silence_threshold_dbfs == -60.0

    def test_silence_threshold_empty_uses_default(self, monkeypatch):
        """Empty WHISPER_SILENCE_THRESHOLD_DBFS falls back to the default."""
        monkeypatch.setenv("WHISPER_SILENCE_THRESHOLD_DBFS", "")
        assert _load_whisper_config_from_env().silence_threshold_dbfs == -50.0

    def test_task_from_env(self, monkeypatch):
        """WHISPER_TASK sets the transcription task."""
        monkeypatch.setenv("WHISPER_TASK", "translate")
        assert _load_whisper_config_from_env().task == "translate"

    def test_timeout_invalid_raises(self, monkeypatch):
        """Invalid WHISPER_TIMEOUT raises ValueError."""
        monkeypatch.setenv("WHISPER_TIMEOUT", "not-a-number")
        with pytest.raises(ValueError):
            _load_whisper_config_from_env()

    def test_temperature_invalid_raises(self, monkeypatch):
        """Invalid WHISPER_TEMPERATURE raises ValueError."""
        monkeypatch.setenv("WHISPER_TEMPERATURE", "abc")
        with pytest.raises(ValueError):
            _load_whisper_config_from_env()


class TestAppConfig:
    """Tests for the AppConfig aggregate model."""

    def test_defaults(self, env_isolator):
        """AppConfig aggregates all config sections with defaults."""
        app = AppConfig()
        assert isinstance(app.database, DatabaseConfig)
        assert isinstance(app.audio, AudioConfig)
        assert isinstance(app.openai, WhisperConfig)
        assert app.copy_to_clipboard is True

    def test_openai_field_reads_env(self, monkeypatch):
        """AppConfig.openai is populated from WHISPER_* env vars."""
        monkeypatch.setenv("WHISPER_PROVIDER", "groq")
        assert AppConfig().openai.provider == "groq"


class TestLoadConfig:
    """Tests for the load_config function."""

    @staticmethod
    def _delete_api_key_env(monkeypatch):
        """Delete all provider API key environment variables."""
        for key in (
            "OPENAI_API_KEY",
            "GROQ_API_KEY",
            "TOGETHER_API_KEY",
            "DEEPINFRA_API_KEY",
            "OPENROUTER_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)

    @staticmethod
    def _delete_whisper_env(monkeypatch):
        """Delete all WHISPER_* environment variables."""
        for key in list(os.environ):
            if key.startswith("WHISPER_"):
                monkeypatch.delenv(key, raising=False)

    def test_load_config_with_api_key(self, monkeypatch):
        """load_config succeeds when OPENAI_API_KEY is present."""
        self._delete_whisper_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        config = load_config()
        assert isinstance(config, AppConfig)

    def test_load_config_missing_api_key_raises(self, monkeypatch):
        """load_config raises ValueError when no API key is available."""
        self._delete_api_key_env(monkeypatch)
        self._delete_whisper_env(monkeypatch)
        with pytest.raises(ValueError, match="API key not found"):
            load_config()

    def test_load_config_groq_provider(self, monkeypatch):
        """load_config resolves GROQ_API_KEY for the groq provider."""
        self._delete_api_key_env(monkeypatch)
        self._delete_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", "groq")
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        load_config()  # should not raise

    def test_load_config_local_provider_succeeds_without_key(self, monkeypatch):
        """load_config succeeds for the local provider without a key.

        LOCAL declares env_var=None in PROVIDER_DEFAULTS, so no key is
        resolved from the environment and no key is required.
        """
        self._delete_api_key_env(monkeypatch)
        self._delete_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", "local")
        config = load_config()
        assert config.openai.api_key == ""

    def test_load_config_invalid_provider_falls_back_to_custom(self, monkeypatch):
        """Invalid provider falls back to CUSTOM and succeeds without a key.

        CUSTOM declares env_var=None in PROVIDER_DEFAULTS, so the fallback
        never consults OPENAI_API_KEY; config loading succeeds with no key.
        """
        self._delete_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", "invalid")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        config = load_config()
        assert config.openai.api_key == ""

    def test_load_config_custom_provider_no_key_succeeds(self, monkeypatch):
        """load_config succeeds for the custom provider without any API key.

        CUSTOM is a user-configured endpoint (possibly local/auth-free) and
        declares env_var=None, so no provider env var is consulted and no
        key is required.
        """
        self._delete_api_key_env(monkeypatch)
        self._delete_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", "custom")
        config = load_config()
        assert config.openai.api_key == ""

    def test_load_config_whisper_api_key_takes_priority(self, monkeypatch):
        """WHISPER_API_KEY is checked before the provider env var."""
        self._delete_api_key_env(monkeypatch)
        monkeypatch.setenv("WHISPER_API_KEY", "whisper-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        load_config()  # should not raise


class TestResolveModel:
    """Tests for the provider-aware resolve_model() helper."""

    @pytest.mark.parametrize("provider", [p.value for p in WhisperProvider])
    def test_provider_default_when_unset(self, provider):
        """An empty explicit model resolves to the provider's default."""
        assert resolve_model(provider, "") == PROVIDER_DEFAULTS[WhisperProvider(provider)]["default_model"]

    def test_unknown_provider_uses_custom_default(self):
        """Unknown provider strings resolve to the CUSTOM default."""
        assert resolve_model("unknown", "") == PROVIDER_DEFAULTS[WhisperProvider.CUSTOM]["default_model"]

    def test_explicit_model_wins(self):
        """A non-empty explicit model overrides the provider default."""
        assert resolve_model("openrouter", "openai/whisper-1") == "openai/whisper-1"

    def test_explicit_model_is_trimmed(self):
        """Leading/trailing whitespace is stripped from the explicit model."""
        assert resolve_model("openai", "  whisper-large-v3  ") == "whisper-large-v3"

    @pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
    def test_blank_falls_back_to_default(self, blank):
        """Empty and whitespace-only values are treated as 'not configured'."""
        assert resolve_model("openrouter", blank) == "microsoft/mai-transcribe-2"

    def test_enum_member_is_valid_str_argument(self):
        """WhisperProvider members (StrEnum) are accepted as plain str."""
        assert resolve_model(WhisperProvider.GROQ, "") == "whisper-large-v3"


class TestValidateModel:
    """Tests for validate_model()."""

    @pytest.mark.parametrize("provider", [p.value for p in WhisperProvider])
    def test_empty_model_rejected_for_every_provider(self, provider):
        """An empty effective model raises for any provider."""
        with pytest.raises(ValueError, match="No transcription model configured"):
            validate_model(provider, "")

    def test_empty_model_message_is_actionable(self):
        """The empty-model error names the provider and the remediation."""
        with pytest.raises(ValueError) as excinfo:
            validate_model("groq", "")
        message = str(excinfo.value)
        assert "groq" in message
        assert "WHISPER_MODEL" in message
        assert "provider default" in message

    @pytest.mark.parametrize("blank", ["   ", "\t", "\n", "  \t\n "])
    def test_whitespace_only_model_rejected(self, blank):
        """A whitespace-only model is rejected just like an empty one."""
        with pytest.raises(ValueError, match="No transcription model configured"):
            validate_model("groq", blank)

    def test_openrouter_unnamespaced_rejected(self):
        """OpenRouter models without a '/' namespace raise with examples."""
        with pytest.raises(ValueError) as excinfo:
            validate_model("openrouter", "whisper-1")
        message = str(excinfo.value)
        assert "whisper-1" in message
        assert "microsoft/mai-transcribe-2" in message
        assert "openai/whisper-1" in message

    def test_openrouter_namespaced_accepted(self):
        """A namespaced OpenRouter model passes validation."""
        validate_model("openrouter", "microsoft/mai-transcribe-2")
        validate_model("openrouter", "openai/whisper-1")

    @pytest.mark.parametrize("provider", ["groq", "together", "deepinfra", "local", "custom"])
    def test_non_openrouter_not_namespace_validated(self, provider):
        """Providers other than OpenRouter accept un-namespaced models."""
        validate_model(provider, "whisper-large-v3")
        validate_model(provider, "base.en")


class TestWhisperConfigModelResolution:
    """The WhisperConfig validator resolves and validates the model."""

    def test_default_openai_model_unchanged(self, env_isolator):
        """OpenAI still resolves to whisper-1 (unchanged behavior)."""
        assert WhisperConfig().model == "whisper-1"

    def test_direct_openrouter_construction_resolves_default(self, env_isolator):
        """WhisperConfig(provider='openrouter') resolves without env reads."""
        assert WhisperConfig(provider="openrouter").model == "microsoft/mai-transcribe-2"

    def test_explicit_model_wins_and_is_trimmed(self, env_isolator):
        """An explicit model overrides the default and is trimmed."""
        assert WhisperConfig(provider="openai", model="  whisper-large-v3  ").model == "whisper-large-v3"

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_model_falls_back(self, env_isolator, blank):
        """Blank/whitespace models fall back to the provider default."""
        assert WhisperConfig(provider="openrouter", model=blank).model == "microsoft/mai-transcribe-2"

    def test_openrouter_unnamespaced_raises(self, env_isolator):
        """An un-namespaced OpenRouter override fails at construction."""
        with pytest.raises(ValueError) as excinfo:
            WhisperConfig(provider="openrouter", model="whisper-1")
        message = str(excinfo.value)
        assert "whisper-1" in message
        assert "microsoft/mai-transcribe-2" in message

    def test_groq_unnamespaced_accepted(self, env_isolator):
        """Groq models without a slash are accepted."""
        assert WhisperConfig(provider="groq", model="whisper-large-v3").model == "whisper-large-v3"

    def test_custom_unnamespaced_accepted(self, env_isolator):
        """Custom provider models without a slash are accepted."""
        assert WhisperConfig(provider="custom", model="base.en").model == "base.en"

    def test_unknown_provider_uses_custom_default(self, env_isolator):
        """An unknown provider string resolves to the custom default model."""
        assert WhisperConfig(provider="unknown").model == "whisper-1"

    def test_validator_rejects_empty_effective_model(self, env_isolator, monkeypatch):
        """The validator path rejects an empty effective model.

        The resolve step normally substitutes a default, so this path is a
        defense-in-depth guard reached by bypassing the table entry.
        """
        monkeypatch.setitem(
            PROVIDER_DEFAULTS,
            WhisperProvider.OPENAI,
            {"base_url": None, "env_var": None, "default_model": ""},
        )
        with pytest.raises(ValueError, match="No transcription model configured"):
            WhisperConfig(provider="openai", model="")


class TestModelResolutionThroughEnv:
    """load_config() resolves per-provider defaults and overrides."""

    @staticmethod
    def _clear_whisper_env(monkeypatch):
        for key in list(os.environ):
            if key.startswith("WHISPER_"):
                monkeypatch.delenv(key, raising=False)

    @pytest.mark.parametrize(
        ("provider", "expected"),
        [
            ("openai", "whisper-1"),
            ("groq", "whisper-large-v3"),
            ("together", "whisper-1"),
            ("deepinfra", "whisper-1"),
            ("openrouter", "microsoft/mai-transcribe-2"),
            ("local", "whisper-1"),
            ("custom", "whisper-1"),
            ("unknown", "whisper-1"),
        ],
    )
    def test_per_provider_default(self, monkeypatch, provider, expected):
        """load_config(require_api_key=False) resolves each provider's default."""
        self._clear_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", provider)
        config = load_config(require_api_key=False)
        assert config.openai.model == expected

    def test_explicit_model_wins(self, monkeypatch):
        """An explicit WHISPER_MODEL overrides the provider default."""
        self._clear_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", "openrouter")
        monkeypatch.setenv("WHISPER_MODEL", "openai/whisper-1")
        config = load_config(require_api_key=False)
        assert config.openai.model == "openai/whisper-1"

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_model_falls_back(self, monkeypatch, blank):
        """Empty/whitespace WHISPER_MODEL falls back to the provider default."""
        self._clear_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", "openrouter")
        monkeypatch.setenv("WHISPER_MODEL", blank)
        config = load_config(require_api_key=False)
        assert config.openai.model == "microsoft/mai-transcribe-2"

    def test_absent_model_falls_back(self, monkeypatch):
        """An absent WHISPER_MODEL falls back to the provider default."""
        self._clear_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", "groq")
        config = load_config(require_api_key=False)
        assert config.openai.model == "whisper-large-v3"

    def test_openrouter_unnamespaced_raises(self, monkeypatch):
        """WHISPER_PROVIDER=openrouter + un-namespaced model fails fast."""
        self._clear_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", "openrouter")
        monkeypatch.setenv("WHISPER_MODEL", "whisper-1")
        with pytest.raises(ValueError) as excinfo:
            load_config(require_api_key=False)
        message = str(excinfo.value)
        assert "whisper-1" in message
        assert "microsoft/mai-transcribe-2" in message

    def test_resolved_model_reaches_appconfig(self, monkeypatch):
        """The resolved model reaches AppConfig.openai via the factory chain."""
        self._clear_whisper_env(monkeypatch)
        monkeypatch.setenv("WHISPER_PROVIDER", "openrouter")
        app = AppConfig()
        assert app.openai.model == "microsoft/mai-transcribe-2"


class TestDotenvImportPurity:
    """Importing whisper_dictate.config must not mutate the environment.

    load_dotenv() used to run at module import time (config.py module
    level), so a bare ``import whisper_dictate.config`` could rewrite
    os.environ. Since S2 it runs only in the composition root
    (whisper_dictate.app.bootstrap), which every entry point (CLI, toggle
    module/console script) calls; the config module import and load_config()
    itself stay side-effect-free.

    These tests run real subprocesses with a .env file present in the working
    directory, because in-process imports would already be cached. The child
    process gets a scrubbed environment (_run_python) so results reflect the
    code under test, not whatever WHISPER_*/provider variables the developer's
    shell happens to export.
    """

    _PROBE_DOTENV = "WHISPER_MODEL=probe-model-from-dotenv\n"

    # Environment variables the child interpreter needs to start and import the
    # package. Everything else is deliberately dropped: an exported WHISPER_* or
    # provider key in the developer's shell would otherwise satisfy a probe
    # assertion (or cause one to fail) without the code under test doing
    # anything, because load_dotenv(override=False) keeps existing values.
    _ENV_ALLOWLIST = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",  # Windows: required by os/socket initialization
        "COMSPEC",
        "PATHEXT",
        "VIRTUAL_ENV",
    )

    def _run_python(self, cwd: Path, code: str) -> subprocess.CompletedProcess[str]:
        repo_root = Path(__file__).resolve().parents[2]
        env = {name: os.environ[name] for name in self._ENV_ALLOWLIST if name in os.environ}
        # Repo root keeps `tests.*` importable; the package itself resolves from
        # the virtualenv that owns sys.executable.
        env["PYTHONPATH"] = str(repo_root)
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_bare_import_does_not_mutate_os_environ(self, tmp_path):
        """A bare `import whisper_dictate.config` leaves os.environ identical,
        even with a .env file in the working directory."""
        (tmp_path / ".env").write_text(self._PROBE_DOTENV)
        code = (
            "import os, json\n"
            "before = dict(os.environ)\n"
            "import whisper_dictate.config\n"
            "after = dict(os.environ)\n"
            "print(json.dumps({'identical': before == after,\n"
            "                  'probe_present': 'WHISPER_MODEL' in after and\n"
            "                  after.get('WHISPER_MODEL', '').endswith('from-dotenv')}))\n"
        )
        result = self._run_python(tmp_path, code)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout.strip())
        assert payload["identical"] is True, "importing whisper_dictate.config mutated os.environ"
        assert payload["probe_present"] is False

    def test_load_config_does_not_load_dotenv(self, tmp_path):
        """load_config() is side-effect-free: .env values are NOT picked up
        without the explicit bootstrap step.

        The child env is scrubbed (see _run_python), so the default model is
        the only acceptable answer: a match here means neither the cwd .env
        nor an exported WHISPER_MODEL leaked into the configuration.
        """
        (tmp_path / ".env").write_text(self._PROBE_DOTENV)
        code = (
            "from whisper_dictate.config import load_config\n"
            "config = load_config(require_api_key=False)\n"
            "print(config.openai.model)\n"
        )
        result = self._run_python(tmp_path, code)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "whisper-1", (
            f"load_config() picked up .env or an exported WHISPER_MODEL: {result.stdout.strip()!r}"
        )

    def test_bootstrap_loads_dotenv_from_explicit_path(self, tmp_path):
        """bootstrap() loads the .env named by dotenv_path, not the cwd one.

        The probe .env lives in a subdirectory while the child process runs in
        an empty directory, so python-dotenv's own discovery finds nothing:
        under ``python -c`` find_dotenv() starts at os.getcwd(). If bootstrap()
        ignored dotenv_path the model would fall back to the default
        "whisper-1" and this test fails — that is the discrimination the old
        cwd-based test lacked.
        """
        env_dir = tmp_path / "envs"
        env_dir.mkdir()
        probe_model = "probe-model-from-explicit-path"
        probe_dotenv = env_dir / ".env"
        probe_dotenv.write_text(f"WHISPER_MODEL={probe_model}\n")

        run_dir = tmp_path / "cwd-without-a-dotenv"
        run_dir.mkdir()
        code = (
            "from whisper_dictate.app import bootstrap\n"
            f"config = bootstrap(require_api_key=False, dotenv_path={str(probe_dotenv)!r})\n"
            "print(config.openai.model)\n"
        )
        result = self._run_python(run_dir, code)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == probe_model
