"""Configuration management for whisper-dictate."""

import os
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class WhisperProvider(StrEnum):
    """WHY THIS EXISTS: Users need to select from known Whisper API providers
    (OpenAI, Groq, Together AI, local servers) with sensible defaults.

    RESPONSIBILITY: Enumerate known Whisper provider types.
    BOUNDARIES:
    - DOES: Define provider identifiers used in configuration
    - DOES NOT: Contain provider implementation details
    """

    OPENAI = "openai"
    GROQ = "groq"
    TOGETHER = "together"
    DEEPINFRA = "deepinfra"
    LOCAL = "local"
    CUSTOM = "custom"


# Maps provider enum to default base_url and environment variable for API key
PROVIDER_DEFAULTS: dict[WhisperProvider, dict] = {
    WhisperProvider.OPENAI: {
        "base_url": None,  # OpenAI SDK default
        "env_var": "OPENAI_API_KEY",
    },
    WhisperProvider.GROQ: {
        "base_url": "https://api.groq.com/openai/v1",
        "env_var": "GROQ_API_KEY",
    },
    WhisperProvider.TOGETHER: {
        "base_url": "https://api.together.xyz/v1",
        "env_var": "TOGETHER_API_KEY",
    },
    WhisperProvider.DEEPINFRA: {
        "base_url": "https://api.deepinfra.com/v1/openai",
        "env_var": "DEEPINFRA_API_KEY",
    },
    WhisperProvider.LOCAL: {
        "base_url": "http://localhost:8000/v1",
        "env_var": None,  # No auth needed for local servers
    },
    WhisperProvider.CUSTOM: {
        "base_url": None,  # Must be set explicitly by user
        "env_var": None,
    },
}


class DatabaseConfig(BaseModel):
    """WHY THIS EXISTS: Database configuration needs to follow XDG
    Base Directory spec for proper Linux integration.

    RESPONSIBILITY: Define database storage settings.
    BOUNDARIES:
    - DOES: Provide path configuration for database and recordings
    - DOES NOT: Handle actual database operations
    """

    path: Path | None = Field(
        default=None, description="Database file path (defaults to XDG data directory)"
    )
    recordings_path: Path | None = Field(
        default=None,
        description="Recordings directory path (defaults to XDG data directory)",
    )
    log_retention_days: int = Field(
        default=30,
        description="Number of days to retain database logs",
    )
    min_free_space_mb: int = Field(
        default=100,
        description="Minimum free disk space required in MB before recording",
    )

    def get_database_path(self) -> Path:
        """Get the full database file path.

        Returns:
            Path: Full path to the database file
        """
        if self.path:
            return self.path

        # Use XDG Base Directory spec: ~/.local/share/whisper-dictate/
        data_dir = (
            Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            / "whisper-dictate"
        )
        return data_dir / "whisper-dictate.db"

    def get_recordings_path(self) -> Path:
        """Get the full recordings directory path.

        Returns:
            Path: Full path to the recordings directory
        """
        if self.recordings_path:
            return self.recordings_path

        # Use XDG Base Directory spec: ~/.local/share/whisper-dictate/recordings/
        return (
            Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            / "whisper-dictate"
            / "recordings"
        )


class AudioConfig(BaseModel):
    """WHY THIS EXISTS: Audio recording parameters need to be configurable
    for different environments and use cases.

    RESPONSIBILITY: Define audio recording settings with sensible defaults.
    BOUNDARIES:
    - DOES: Provide typed configuration for audio parameters
    - DOES NOT: Handle actual audio recording or validation
    """

    sample_rate: int = Field(default=16000, description="Audio sample rate in Hz")
    channels: int = Field(default=1, description="Number of audio channels")
    duration: float = Field(
        default=5.0, description="Maximum recording duration in seconds"
    )
    device: int | str | None = Field(
        default=None, description="Audio input device index or name"
    )
    mp3_enabled: bool = Field(
        default=True,
        description="Enable MP3 conversion before API upload. "
        "Reduces file size by 80-90% with no impact on transcription quality. "
        "Set to False to keep original WAV format.",
    )
    mp3_bitrate: str = Field(
        default="128k",
        description="MP3 encoding bitrate (e.g., '64k', '128k', '192k'). "
        "Higher values produce larger files with marginal quality improvement for speech. "
        "'128k' is recommended for voice transcription.",
    )
    keep_wav: bool = Field(
        default=False,
        description="Keep original WAV file after MP3 conversion. "
        "When False (default), WAV is deleted after successful MP3 creation to save space. "
        "Set to True if you need to preserve original recordings.",
    )


class WhisperConfig(BaseModel):
    """WHY THIS EXISTS: Whisper API configuration needs to support any
    OpenAI-compatible provider (OpenAI, Groq, Together AI, local servers).

    RESPONSIBILITY: Manage Whisper API settings for any provider.
    BOUNDARIES:
    - DOES: Store and validate provider configuration
    - DOES NOT: Handle API calls or authentication

    RELATIONSHIPS:
    - USED BY: create_transcriber() factory to build provider instances
    - REPLACES: OpenAIConfig (which is now an alias for backward compatibility)
    """

    provider: str = Field(
        default="openai",
        description="Provider type: openai, groq, together, deepinfra, local, custom",
    )
    api_key: str = Field(
        default="",
        description="API key. If empty, resolved from provider's default env var.",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom API base URL. Overrides provider default.",
    )
    model: str = Field(
        default="whisper-1",
        description="Model name (may differ per provider, e.g. 'whisper-large-v3' for Groq)",
    )
    timeout: float = Field(
        default=30.0,
        description="API request timeout in seconds",
    )
    language: str | None = Field(
        default=None,
        description="Language hint as ISO 639-1 code (e.g. 'en', 'de'). "
        "If None, Whisper auto-detects the language.",
    )
    temperature: float = Field(
        default=0.0,
        description="Sampling temperature (0.0 = deterministic, higher = more creative). "
        "For transcription, 0.0 is recommended.",
    )
    silence_threshold_dbfs: float | None = Field(
        default=-50.0,
        description="Pre-transcription silence detection threshold in dBFS. "
        "Audio below this RMS energy level is considered silent and skipped "
        "to prevent Whisper hallucinations. Set to None to disable silence detection.",
    )
    task: str | None = Field(
        default=None,
        description="Whisper task to perform. None uses provider default ('transcribe'). "
        "Allowed values: 'transcribe', 'translate'. Only affects providers that support "
        "this parameter (e.g., DeepInfra).",
    )


# Backward compatibility: OpenAIConfig is now an alias for WhisperConfig
OpenAIConfig = WhisperConfig


def _load_whisper_config_from_env() -> WhisperConfig:
    """Load WhisperConfig from WHISPER_* environment variables.

    Env vars supported:
    - WHISPER_PROVIDER: Provider type (openai, groq, together, deepinfra, local, custom). Default: "openai"
    - WHISPER_API_KEY: Explicit API key. Default: "" (falls back to provider-specific env var)
    - WHISPER_BASE_URL: Custom API base URL. Default: None (uses provider default)
    - WHISPER_MODEL: Model name. Default: "whisper-1"
    - WHISPER_TIMEOUT: Request timeout in seconds. Default: 30.0
    - WHISPER_LANGUAGE: Language hint (ISO 639-1). Default: None (auto-detect)
    - WHISPER_TEMPERATURE: Sampling temperature. Default: 0.0
    - WHISPER_TASK: Whisper task ('transcribe' or 'translate'). Default: None (provider default)

    Returns:
        WhisperConfig: Configuration loaded from environment variables.
    """
    silence_threshold_env = os.getenv("WHISPER_SILENCE_THRESHOLD_DBFS")
    silence_threshold = float(silence_threshold_env) if silence_threshold_env else -50.0

    return WhisperConfig(
        provider=os.getenv("WHISPER_PROVIDER", "openai"),
        api_key=os.getenv("WHISPER_API_KEY", ""),
        base_url=os.getenv("WHISPER_BASE_URL") or None,
        model=os.getenv("WHISPER_MODEL", "whisper-1"),
        timeout=float(os.getenv("WHISPER_TIMEOUT", "30.0")),
        language=os.getenv("WHISPER_LANGUAGE") or None,
        temperature=float(os.getenv("WHISPER_TEMPERATURE", "0.0")),
        silence_threshold_dbfs=silence_threshold,
        task=os.getenv("WHISPER_TASK") or None,
    )


class AppConfig(BaseModel):
    """WHY THIS EXISTS: Application configuration needs to be centralized
    for easy management and testing.

    RESPONSIBILITY: Aggregate all configuration sections.
    BOUNDARIES:
    - DOES: Provide typed access to all configuration
    - DOES NOT: Handle configuration persistence or validation
    """

    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig())
    audio: AudioConfig = Field(default_factory=AudioConfig)
    openai: OpenAIConfig = Field(default_factory=_load_whisper_config_from_env)
    log_level: str = Field(default="INFO", description="Logging level")
    copy_to_clipboard: bool = Field(
        default=True, description="Copy transcription to clipboard"
    )


def load_config() -> AppConfig:
    """WHY THIS EXISTS: Configuration loading needs to be centralized
    to ensure consistent initialization across the application.

    RESPONSIBILITY: Load and validate configuration from environment.
    BOUNDARIES:
    - DOES: Load configuration from environment variables
    - DOES NOT: Handle configuration file management

    Returns:
        AppConfig: Validated application configuration

    Raises:
        ValueError: If required configuration is missing
    """
    config = AppConfig()

    # Resolve API key: explicit config > provider env var
    api_key = config.openai.api_key
    if not api_key:
        from whisper_dictate.config import PROVIDER_DEFAULTS, WhisperProvider

        try:
            provider_enum = WhisperProvider(config.openai.provider)
        except ValueError:
            provider_enum = WhisperProvider.CUSTOM
        defaults = PROVIDER_DEFAULTS.get(provider_enum, {})
        env_var = defaults.get("env_var", "OPENAI_API_KEY")
        api_key = os.getenv(env_var, "")

    if not api_key:
        raise ValueError(
            "API key not found. Set the appropriate environment variable "
            "(OPENAI_API_KEY, GROQ_API_KEY, etc.) or configure api_key explicitly."
        )

    return config
