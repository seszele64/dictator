"""Configuration management for whisper-dictate."""

import logging
import os
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


class WhisperProvider(StrEnum):
    """WHY THIS EXISTS: Users need to select from known Whisper API providers
    (OpenAI, Groq, Together AI, OpenRouter, local servers) with sensible
    defaults.

    RESPONSIBILITY: Enumerate known Whisper provider types.
    BOUNDARIES:
    - DOES: Define provider identifiers used in configuration
    - DOES NOT: Contain provider implementation details
    """

    OPENAI = "openai"
    GROQ = "groq"
    TOGETHER = "together"
    DEEPINFRA = "deepinfra"
    OPENROUTER = "openrouter"
    LOCAL = "local"
    CUSTOM = "custom"


class ProviderDefaults(TypedDict):
    """Per-provider configuration facts.

    - ``base_url``: default API base URL, or None when the provider has no
      sensible default (OpenAI uses the SDK default; custom must be set by the
      user).
    - ``env_var``: environment variable holding the provider's API key, or None
      for keyless providers (local, custom).
    - ``default_model``: transcription model used when ``WHISPER_MODEL`` is
      unset, empty, or whitespace-only. Always a concrete string.
    """

    base_url: str | None
    env_var: str | None
    default_model: str


# Maps provider enum to default base_url, API-key environment variable, and
# default transcription model. ``default_model`` is the fallback used by
# resolve_model() whenever no explicit WHISPER_MODEL is configured.
PROVIDER_DEFAULTS: dict[WhisperProvider, ProviderDefaults] = {
    WhisperProvider.OPENAI: {
        "base_url": None,  # OpenAI SDK default
        "env_var": "OPENAI_API_KEY",
        "default_model": "whisper-1",
    },
    WhisperProvider.GROQ: {
        "base_url": "https://api.groq.com/openai/v1",
        "env_var": "GROQ_API_KEY",
        "default_model": "whisper-large-v3",
    },
    WhisperProvider.TOGETHER: {
        "base_url": "https://api.together.xyz/v1",
        "env_var": "TOGETHER_API_KEY",
        "default_model": "whisper-1",
    },
    WhisperProvider.DEEPINFRA: {
        "base_url": "https://api.deepinfra.com/v1/openai",
        "env_var": "DEEPINFRA_API_KEY",
        "default_model": "whisper-1",
    },
    WhisperProvider.OPENROUTER: {
        "base_url": "https://openrouter.ai/api/v1",
        "env_var": "OPENROUTER_API_KEY",
        "default_model": "microsoft/mai-transcribe-2",
    },
    WhisperProvider.LOCAL: {
        "base_url": "http://localhost:8000/v1",
        "env_var": None,  # No auth needed for local servers
        "default_model": "whisper-1",
    },
    WhisperProvider.CUSTOM: {
        "base_url": None,  # Must be set explicitly by user
        "env_var": None,
        "default_model": "whisper-1",
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

    path: Path | None = Field(default=None, description="Database file path (defaults to XDG data directory)")
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

        Delegates to AppPaths.database_path() so the XDG base-directory
        resolution lives in exactly one place (explicit path override still
        wins).

        Returns:
            Path: Full path to the database file
        """
        return AppPaths().database_path(self)

    def get_recordings_path(self) -> Path:
        """Get the full recordings directory path.

        Delegates to AppPaths.recordings_dir() so the XDG base-directory
        resolution lives in exactly one place (explicit override still wins).

        Returns:
            Path: Full path to the recordings directory
        """
        return AppPaths().recordings_dir(self)


def _xdg_data_home() -> Path:
    """Return $XDG_DATA_HOME or its XDG Base Directory spec default (~/.local/share)."""
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _xdg_state_home() -> Path:
    """Return $XDG_STATE_HOME or its XDG Base Directory spec default (~/.local/state)."""
    return Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))


class AppPaths(BaseModel):
    """WHY THIS EXISTS: Every filesystem location (database, recordings, logs,
    backups, legacy dotfiles) used to be resolved independently in four
    modules, duplicating the XDG base-directory logic and drifting apart
    (logs lived under the data home, legacy files under $HOME). A single
    frozen model keeps one source of truth and pre-wires a future composition
    root that passes paths explicitly instead of reading globals.

    RESPONSIBILITY: Resolve application filesystem paths from XDG env vars.
    BOUNDARIES:
    - DOES: Resolve data_home / log_dir / legacy file paths from the
      environment at instantiation time, expose derived backup_dir and
      log_file, and provide effective database/recordings resolvers that
      honor DatabaseConfig overrides
    - DOES NOT: Create directories, read or write any file, or perform I/O
    """

    model_config = ConfigDict(frozen=True)

    data_home: Path = Field(
        default_factory=lambda: _xdg_data_home() / "whisper-dictate",
        description="XDG data home ($XDG_DATA_HOME or ~/.local/share) for "
        "whisper-dictate; contains the database, recordings and backups",
    )
    log_dir: Path = Field(
        default_factory=lambda: _xdg_state_home() / "whisper-dictate" / "logs",
        description="Log directory ($XDG_STATE_HOME or ~/.local/state). Logs "
        "are state, not data, so they live under XDG_STATE_HOME — previously "
        "they were written under the data home. Old logs are not migrated.",
    )
    legacy_state_file: Path = Field(
        default_factory=lambda: Path.home() / ".whisper-dictate-state",
        description="Legacy toggle state marker in $HOME — the toggle's "
        "runtime fallback file AND the migration source path (shared)",
    )
    legacy_pid_file: Path = Field(
        default_factory=lambda: Path.home() / ".whisper-dictate-pid",
        description="Legacy arecord PID file in $HOME — the toggle's runtime "
        "fallback file AND the migration source path (shared)",
    )
    legacy_audio_file: Path = Field(
        default_factory=lambda: Path.home() / ".whisper-dictate-audio.wav",
        description="Legacy audio scratch file in $HOME — the toggle's "
        "runtime fallback file AND the migration source path (shared)",
    )

    @property
    def backup_dir(self) -> Path:
        """Backup directory inside the data home (always consistent with it)."""
        return self.data_home / "backups"

    @property
    def log_file(self) -> Path:
        """Path of the main application log file inside log_dir."""
        return self.log_dir / "whisper-dictate.log"

    def database_path(self, config: DatabaseConfig | None = None) -> Path:
        """Effective database file path: explicit override wins over XDG default.

        Args:
            config: Database config carrying an optional explicit path; when
                None, default configuration (XDG data home) is used.

        Returns:
            Path: Full path to the database file
        """
        db_config = config if config is not None else DatabaseConfig()
        return db_config.path if db_config.path else self.data_home / "whisper-dictate.db"

    def recordings_dir(self, config: DatabaseConfig | None = None) -> Path:
        """Effective recordings directory: explicit override wins over XDG default.

        Args:
            config: Database config carrying an optional explicit recordings
                path; when None, default configuration (XDG data home) is used.

        Returns:
            Path: Full path to the recordings directory
        """
        db_config = config if config is not None else DatabaseConfig()
        if db_config.recordings_path:
            return db_config.recordings_path
        return self.data_home / "recordings"


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
    duration: float = Field(default=5.0, description="Maximum recording duration in seconds")
    device: int | str | None = Field(default=None, description="Audio input device index or name")
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
    OpenAI-compatible provider (OpenAI, Groq, Together AI, DeepInfra,
    OpenRouter, local servers).

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
        description="Provider type: openai, groq, together, deepinfra, openrouter, local, custom",
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
        default="",
        description="Model name (may differ per provider, e.g. 'whisper-large-v3' for Groq). "
        "Empty means 'use the provider default' and is resolved at validation time.",
    )
    timeout: float = Field(
        default=30.0,
        description="API request timeout in seconds",
    )
    language: str | None = Field(
        default=None,
        description="Language hint as ISO 639-1 code (e.g. 'en', 'de'). If None, Whisper auto-detects the language.",
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

    @model_validator(mode="after")
    def _resolve_model(self) -> "WhisperConfig":
        """Resolve the provider-specific model and validate it in place.

        WHY the resolution is stored on the model instead of exposed as a
        computed property: transcript history records the effective model
        verbatim (`model_used` / `openai_model` read `config.openai.model`),
        so the resolved value must persist on the instance rather than be
        recomputed by each consumer.

        WHY `return self` is required: a `mode="after"` model validator must
        return the model instance; returning None is a validation error.

        Because this lives on the model, both real entry points — direct
        `WhisperConfig(...)` construction and `_load_whisper_config_from_env()`
        — resolve and validate identically.
        """
        self.model = resolve_model(self.provider, self.model)
        validate_model(self.provider, self.model)
        return self


# Backward compatibility: OpenAIConfig is now an alias for WhisperConfig
OpenAIConfig = WhisperConfig


class PostProcessConfig(BaseModel):
    """WHY THIS EXISTS: Prompt-driven post-processing talks to an
    OpenAI-compatible chat-completions endpoint, which is a different
    request/response contract (and often a different model) than audio
    transcription. Keeping the chat block in its own model makes the
    isolation from ``WHISPER_*`` explicit and enforced by construction.

    RESPONSIBILITY: Store chat-processing settings.
    BOUNDARIES:
    - DOES: Hold provider, model, base URL, key, timeout and preset prompt
    - DOES NOT: Resolve provider facts, validate, or construct clients

    RELATIONSHIPS:
    - USED BY: validate_post_process_config() and create_post_processor()
    """

    provider: str = Field(
        default="openai",
        description="Chat provider: openai, groq, together, deepinfra, openrouter, local, custom",
    )
    model: str = Field(
        default="",
        description="Chat model name (required; no default and never derived from "
        "WHISPER_MODEL or the provider's transcription default_model).",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom chat API base URL. Overrides the provider default.",
    )
    api_key: str = Field(
        default="",
        description="Chat API key. If empty, resolved from the provider's default env var.",
    )
    timeout: float = Field(
        default=60.0,
        description="Chat request timeout in seconds, passed to the OpenAI client.",
    )
    prompt: str = Field(
        default="",
        description="Preset prompt used to prefill the interactive launcher and as a "
        "headless fallback when no launcher is available.",
    )


def _load_post_process_config_from_env() -> PostProcessConfig:
    """Load PostProcessConfig from POST_PROCESS_* environment variables.

    Reads ONLY the ``POST_PROCESS_*`` variables — never ``WHISPER_MODEL`` or any
    other ``WHISPER_*`` value — so chat processing can never inherit a
    transcription model or key.

    Env vars supported:
    - POST_PROCESS_PROVIDER: Chat provider. Default: "openai"
    - POST_PROCESS_MODEL: Chat model (required at validation time). Default: ""
    - POST_PROCESS_BASE_URL: Custom base URL. Default: None (provider default)
    - POST_PROCESS_API_KEY: Explicit key. Default: "" (provider env var fallback)
    - POST_PROCESS_TIMEOUT: Request timeout in seconds. Default: 60.0
    - POST_PROCESS_PROMPT: Preset prompt. Default: ""

    The timeout is parsed defensively: because this loader runs during
    ``AppConfig`` construction, a non-numeric, zero, or negative value must not
    make unrelated commands (``info``, ``history list``) fail at startup. Such
    values fall back to 60.0 with a warning naming the variable.

    Returns:
        PostProcessConfig: Configuration loaded from environment variables.
    """
    raw_timeout = os.getenv("POST_PROCESS_TIMEOUT")
    timeout = 60.0
    if raw_timeout is not None and raw_timeout != "":
        try:
            parsed = float(raw_timeout)
        except ValueError:
            logger.warning("Invalid POST_PROCESS_TIMEOUT value (non-numeric); falling back to 60.0 seconds")
        else:
            if parsed > 0:
                timeout = parsed
            else:
                logger.warning("Invalid POST_PROCESS_TIMEOUT value (must be positive); falling back to 60.0 seconds")

    return PostProcessConfig(
        provider=os.getenv("POST_PROCESS_PROVIDER", "openai"),
        model=os.getenv("POST_PROCESS_MODEL") or "",
        base_url=os.getenv("POST_PROCESS_BASE_URL") or None,
        api_key=os.getenv("POST_PROCESS_API_KEY", ""),
        timeout=timeout,
        prompt=os.getenv("POST_PROCESS_PROMPT") or "",
    )


def _load_whisper_config_from_env() -> WhisperConfig:
    """Load WhisperConfig from WHISPER_* environment variables.

    Env vars supported:
    - WHISPER_PROVIDER: Provider type (openai, groq, together, deepinfra, openrouter, local, custom). Default: "openai"
    - WHISPER_API_KEY: Explicit API key. Default: "" (falls back to provider-specific env var)
    - WHISPER_BASE_URL: Custom API base URL. Default: None (uses provider default)
    - WHISPER_MODEL: Model name. Default: empty → provider default
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
        model=os.getenv("WHISPER_MODEL") or "",
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
    post_process: PostProcessConfig = Field(default_factory=_load_post_process_config_from_env)
    copy_to_clipboard: bool = Field(default=True, description="Copy transcription to clipboard")

    @property
    def paths(self) -> AppPaths:
        """Application filesystem paths (single source of truth).

        WHY a computed property instead of a stored field: AppPaths resolves
        the XDG_* environment variables at instantiation time, so returning a
        fresh instance on every access preserves the call-time env semantics
        all path consumers had before centralization — a caller (or test) can
        change XDG_DATA_HOME / XDG_STATE_HOME after this config object was
        built and still see the override. A default_factory field would have
        frozen the env snapshot at AppConfig() construction instead.
        """
        return AppPaths()


def _resolve_provider_enum(provider: str) -> WhisperProvider:
    """Resolve a provider string to a WhisperProvider enum.

    Unknown provider strings fall back to CUSTOM, mirroring
    create_transcriber() so both key-resolution paths stay consistent.
    """
    try:
        return WhisperProvider(provider)
    except ValueError:
        return WhisperProvider.CUSTOM


def resolve_model(provider: str, explicit_model: str) -> str:
    """Resolve the effective transcription model for a provider.

    A non-empty ``explicit_model`` (leading/trailing whitespace stripped) wins;
    otherwise the provider's declared ``default_model`` is returned. Unknown
    provider strings resolve to CUSTOM, so they receive the custom default.

    Both parameters are plain ``str``: ``WhisperProvider`` is a ``StrEnum`` (a
    ``str`` subclass), so enum members are valid arguments. ``explicit_model``
    is never ``None`` here — the only ``None`` originates from
    ``os.getenv("WHISPER_MODEL")`` and is collapsed to ``""`` by ``or ""`` in
    the env loader, and the field default is ``""``.

    Args:
        provider: Provider identifier (case-sensitive, unstripped).
        explicit_model: Configured model, or ``""`` when not configured.

    Returns:
        str: The effective model identifier.

    Raises:
        KeyError: If the resolved provider has no ``PROVIDER_DEFAULTS`` entry —
            a programming error (the table is incomplete), never user input.
    """
    provider_enum = _resolve_provider_enum(provider)
    stripped = explicit_model.strip()
    if stripped:
        return stripped
    return PROVIDER_DEFAULTS[provider_enum]["default_model"]


def validate_model(provider: str, model: str) -> None:
    """Validate an effective model for the selected provider.

    OpenRouter requires namespaced ``vendor/model`` identifiers; every other
    provider has no stable public grammar and is never namespace-validated.
    An empty (or whitespace-only) effective model is rejected for any provider
    as a defense against bypassed defaults.

    Args:
        provider: Provider identifier (case-sensitive, unstripped).
        model: The effective model to validate.

    Raises:
        ValueError: If ``model`` is empty or whitespace-only, or the provider
            is ``openrouter`` and ``model`` has no ``/`` namespace.
    """
    if not model.strip():
        raise ValueError(
            f"No transcription model configured for provider '{provider}'. "
            "Set WHISPER_MODEL to a model your provider supports, or rely on "
            "the provider default."
        )

    if _resolve_provider_enum(provider) == WhisperProvider.OPENROUTER and "/" not in model:
        raise ValueError(
            f"Invalid OpenRouter model '{model}': OpenRouter requires a namespaced "
            "'vendor/model' identifier (e.g. 'microsoft/mai-transcribe-2' or "
            "'openai/whisper-1')."
        )


def _provider_auth_env_var(provider: str) -> str | None:
    """Return the auth env var declared for a provider, if any.

    Providers with no declared env var (local, custom) are keyless by design.
    """
    defaults = PROVIDER_DEFAULTS[_resolve_provider_enum(provider)]
    return defaults["env_var"]


def validate_api_key(config: AppConfig) -> None:
    """WHY THIS EXISTS: API-key validation must be lazy so that non-transcription
    CLI commands (logs, history, migrate) run without a key, while transcription
    paths still fail fast with a helpful message.

    RESPONSIBILITY: Enforce API-key presence for providers that require auth.
    BOUNDARIES:
    - DOES: Resolve the effective key (explicit config > provider env var) and
      raise for auth-requiring providers without one
    - DOES NOT: Mutate config, construct clients, or contact any API

    Args:
        config: Application configuration to validate.

    Raises:
        ValueError: If the provider declares an auth env var (openai, groq,
            together, deepinfra, openrouter) but no API key is configured.
            Keyless providers (local, custom) never raise.
    """
    env_var = _provider_auth_env_var(config.openai.provider)
    api_key = config.openai.api_key
    if not api_key and env_var:
        api_key = os.getenv(env_var, "")

    if not api_key and env_var:
        raise ValueError(
            "API key not found. Set the appropriate environment variable "
            "(OPENAI_API_KEY, GROQ_API_KEY, etc.) or configure api_key explicitly."
        )


def validate_post_process_config(config: PostProcessConfig) -> None:
    """WHY THIS EXISTS: Chat-processing settings must be validated lazily — only
    when the ``process`` command runs — so a missing ``POST_PROCESS_MODEL`` never
    breaks unrelated commands (``info``, ``history list``) that build AppConfig.

    RESPONSIBILITY: Enforce the fixed validation order for chat configuration.
    BOUNDARIES:
    - DOES: Check the model, resolve the provider, resolve the base URL, and
      resolve the API key, reporting only the FIRST failure
    - DOES NOT: Mutate config, construct clients, contact any API, call
      ``_resolve_model()``, or read ``PROVIDER_DEFAULTS[...]["default_model"]``

    The order is pinned so an error always names the earliest missing setting:
    1. non-empty stripped model
    2. provider resolution through ``_resolve_provider_enum()`` (unknown → custom)
    3. effective base URL from ``config.base_url`` or the provider default;
       ``custom`` requires a non-empty result
    4. effective API key from ``config.api_key`` or the provider key env var;
       ``local``/``custom`` are keyless, auth providers require a key

    The provider table is reused for base URL and key env var — provider facts
    shared with transcription — but its ``default_model`` is deliberately never
    consulted: those entries are transcription ids (``whisper-1``, ...) and
    substituting one would send an audio model to a chat endpoint.

    Args:
        config: Chat-processing configuration to validate.

    Raises:
        ValueError: On the first missing/invalid setting, naming the variable.
    """
    # 1. Model: required, no default, no transcription fallback.
    if not config.model.strip():
        raise ValueError(
            "POST_PROCESS_MODEL is required but not set. Set it to a chat model "
            "your provider supports (for example 'gpt-4o-mini' for OpenAI). "
            "Note: 'whisper-1' is a transcription model and cannot be used for "
            "chat processing; WHISPER_MODEL is never reused here."
        )

    # 2. Provider resolution (unknown values become custom).
    provider = _resolve_provider_enum(config.provider)

    # 3. Base URL: explicit override wins, else the provider default.
    defaults = PROVIDER_DEFAULTS[provider]
    effective_base_url = config.base_url or defaults["base_url"]
    if provider == WhisperProvider.CUSTOM and not effective_base_url:
        raise ValueError(
            "POST_PROCESS_BASE_URL is required for the 'custom' provider. "
            "Set it to your OpenAI-compatible chat endpoint (e.g. "
            "https://your-api.example.com/v1)."
        )

    # 4. API key: explicit wins, else the provider env var. local/custom are keyless.
    env_var = defaults["env_var"]
    effective_key = config.api_key
    if not effective_key and env_var:
        effective_key = os.getenv(env_var, "")
    if not effective_key and env_var:
        raise ValueError(
            f"Chat API key not found. Set POST_PROCESS_API_KEY or the provider's environment variable ({env_var})."
        )


def load_config(require_api_key: bool = True) -> AppConfig:
    """WHY THIS EXISTS: Configuration loading needs to be centralized
    to ensure consistent initialization across the application.

    RESPONSIBILITY: Load and validate configuration from environment.
    BOUNDARIES:
    - DOES: Load configuration from environment variables
    - DOES NOT: Handle configuration file management

    Args:
        require_api_key: When True (default), raise ValueError if the
            configured provider declares an auth env var (openai, groq,
            together, deepinfra, openrouter) but no key is available.
            Keyless providers (local, custom) never raise. Pass False for
            non-transcription callers (e.g. database-only CLI commands) that
            must work without any key configured.

    Returns:
        AppConfig: Validated application configuration

    Raises:
        ValueError: If required configuration is missing (see validate_api_key()).
    """
    # NOTE: .env loading deliberately does NOT happen here. Importing
    # whisper_dictate.config must stay side-effect-free (no os.environ
    # mutation); the explicit bootstrap step (whisper_dictate.app.bootstrap)
    # owns load_dotenv() before calling this function.
    config = AppConfig()

    if require_api_key:
        validate_api_key(config)

    return config
