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
)


class TestWhisperProvider:
    """Tests for the WhisperProvider enum."""

    def test_provider_values(self):
        """All 6 enum members have correct string values."""
        assert WhisperProvider.OPENAI == "openai"
        assert WhisperProvider.GROQ == "groq"
        assert WhisperProvider.TOGETHER == "together"
        assert WhisperProvider.DEEPINFRA == "deepinfra"
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
        """PROVIDER_DEFAULTS has exactly the 6 providers as keys."""
        assert set(PROVIDER_DEFAULTS) == set(WhisperProvider)
        assert len(PROVIDER_DEFAULTS) == 6

    def test_provider_defaults_structure(self):
        """Each provider default has base_url and env_var keys."""
        for defaults in PROVIDER_DEFAULTS.values():
            assert "base_url" in defaults
            assert "env_var" in defaults

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
        assert (
            DatabaseConfig(recordings_path=Path("/tmp/recordings")).get_recordings_path()
            == Path("/tmp/recordings")
        )

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
        for key in ("OPENAI_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY", "DEEPINFRA_API_KEY"):
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


class TestDotenvImportPurity:
    """Importing whisper_dictate.config must not mutate the environment.

    load_dotenv() used to run at module import time (config.py module
    level), so a bare ``import whisper_dictate.config`` could rewrite
    os.environ. Since S2 it runs only in the composition root
    (whisper_dictate.app.bootstrap), which every entry point (CLI, root
    toggle script) calls; the config module import and load_config() itself
    stay side-effect-free.

    Both tests run real subprocesses with a .env file present in the working
    directory, because in-process imports would already be cached.
    """

    _PROBE_DOTENV = "WHISPER_MODEL=probe-model-from-dotenv\n"

    def _run_python(self, tmp_path: Path, code: str) -> subprocess.CompletedProcess:
        repo_root = Path(__file__).resolve().parents[2]
        env = {**os.environ, "PYTHONPATH": str(repo_root)}
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp_path,
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
        assert payload["identical"] is True, (
            "importing whisper_dictate.config mutated os.environ"
        )
        assert payload["probe_present"] is False

    def test_load_config_does_not_load_dotenv(self, tmp_path):
        """load_config() is side-effect-free: .env values are NOT picked up
        without the explicit bootstrap step."""
        (tmp_path / ".env").write_text(self._PROBE_DOTENV)
        code = (
            "from whisper_dictate.config import load_config\n"
            "config = load_config(require_api_key=False)\n"
            "print(config.openai.model)\n"
        )
        result = self._run_python(tmp_path, code)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() != "probe-model-from-dotenv"

    def test_bootstrap_loads_dotenv(self, tmp_path):
        """bootstrap() picks up .env values — entry-point behavior is
        preserved now that the composition root owns .env loading."""
        (tmp_path / ".env").write_text(self._PROBE_DOTENV)
        code = (
            "from whisper_dictate.app import bootstrap\n"
            "config = bootstrap(require_api_key=False)\n"
            "print(config.openai.model)\n"
        )
        result = self._run_python(tmp_path, code)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "probe-model-from-dotenv"
