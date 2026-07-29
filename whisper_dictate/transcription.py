"""OpenAI Whisper API integration with strong typing."""

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import openai
from openai import OpenAI

from whisper_dictate.config import OpenAIConfig

if TYPE_CHECKING:
    from whisper_dictate.config import WhisperConfig

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """WHY THIS EXISTS: Provider-specific errors (e.g., openai.APIError) need to be
    wrapped so that consumers don't depend on a specific provider's exception types.

    RESPONSIBILITY: Provide a provider-agnostic error type for transcription failures.
    BOUNDARIES:
    - DOES: Wrap provider errors with provider name and message
    - DOES NOT: Handle retry logic or error recovery
    """

    def __init__(self, message: str, provider: Optional[str] = None) -> None:
        self.provider = provider
        super().__init__(message)


@dataclass
class TranscriptionResult:
    """WHY THIS EXISTS: Transcription results need structured representation
    to provide consistent handling and error information.

    RESPONSIBILITY: Encapsulate transcription results with metadata.
    BOUNDARIES:
    - DOES: Store transcription text and metadata
    - DOES NOT: Handle API calls or file operations
    """

    text: str
    language: Optional[str] = None
    duration: Optional[float] = None
    provider: Optional[str] = None
    silence_detected: bool = False

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        if self.silence_detected:
            return f"TranscriptionResult(text='', silence_detected=True, provider={self.provider})"
        return (
            f"TranscriptionResult(text='{self.text[:50]}...', language={self.language})"
        )


class TranscriptionProvider(ABC):
    """WHY THIS EXISTS: Users need to plug in any Whisper API provider
    (OpenAI, Groq, Together AI, local whisper.cpp, etc.) without changing
    the dictation service code.

    RESPONSIBILITY: Define the contract all Whisper transcription providers must implement.
    BOUNDARIES:
    - DOES: Define the transcribe_audio interface and provider_name property
    - DOES NOT: Implement any specific provider's logic

    RELATIONSHIPS:
    - IMPLEMENTED BY: OpenAICompatibleProvider and future provider classes
    - USED BY: DictationService for provider-agnostic transcription
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name for logging and diagnostics."""
        ...

    @abstractmethod
    def transcribe_audio(self, audio_file: Path) -> TranscriptionResult:
        """Transcribe an audio file.

        Args:
            audio_file: Path to the audio file to transcribe.

        Returns:
            TranscriptionResult with transcribed text and metadata.

        Raises:
            IOError: If audio file cannot be read.
            TranscriptionError: If transcription fails.
        """
        ...


class WhisperTranscriber:
    """WHY THIS EXISTS: OpenAI Whisper API integration needs to be encapsulated
    to provide consistent error handling and configuration management.

    RESPONSIBILITY: Transcribe audio files using OpenAI Whisper API.
    BOUNDARIES:
    - DOES: Handle API calls to OpenAI Whisper
    - DOES NOT: Handle audio recording, file management, or clipboard operations

    RELATIONSHIPS:
    - DEPENDS ON: OpenAIConfig for API settings
    - USED BY: DictationService for transcription
    """

    def __init__(self, config: OpenAIConfig, client: Optional[OpenAI] = None) -> None:
        """Initialize Whisper transcriber with configuration.

        Args:
            config: OpenAI API configuration
            client: Optional OpenAI client for testing (defaults to new instance)
        """
        self.config = config
        self.client = client or OpenAI(api_key=config.api_key)

    def transcribe_audio(self, audio_file: Path) -> TranscriptionResult:
        """WHY THIS EXISTS: Audio transcription needs to be handled consistently
        with proper error handling and result formatting.

        RESPONSIBILITY: Transcribe audio file using OpenAI Whisper API.
        BOUNDARIES:
        - DOES: Make API call and return structured result
        - DOES NOT: Handle file validation or cleanup

        Args:
            audio_file: Path to audio file to transcribe

        Returns:
            TranscriptionResult: Structured transcription result

        Raises:
            openai.APIError: If API call fails
            IOError: If audio file cannot be read
        """
        if not audio_file.exists():
            raise IOError(f"Audio file not found: {audio_file}")

        logger.info(f"Transcribing audio file: {audio_file}")

        try:
            with open(audio_file, "rb") as file:
                response = self.client.audio.transcriptions.create(
                    model=self.config.model, file=file, response_format="json"
                )

            result = TranscriptionResult(
                text=response.text, language=getattr(response, "language", None)
            )

            logger.info(
                f"Transcription completed: {len(result.text)} characters, "
                f"language={result.language}"
            )

            return result

        except openai.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during transcription: {e}")
            raise


def create_transcriber(config: "WhisperConfig") -> TranscriptionProvider:
    """WHY THIS EXISTS: DictationService should not know how to construct
    specific provider implementations. This factory resolves configuration
    to the appropriate provider instance.

    RESPONSIBILITY: Create a TranscriptionProvider from WhisperConfig.
    BOUNDARIES:
    - DOES: Resolve provider defaults, API keys, and base URLs from config
    - DOES NOT: Implement provider-specific transcription logic

    Args:
        config: WhisperConfig with provider settings.

    Returns:
        TranscriptionProvider: Configured provider instance.
    """
    from whisper_dictate.config import PROVIDER_DEFAULTS, WhisperProvider
    from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

    # Resolve provider enum
    try:
        provider_enum = WhisperProvider(config.provider)
    except ValueError:
        provider_enum = WhisperProvider.CUSTOM

    defaults = PROVIDER_DEFAULTS.get(provider_enum, {})

    # Resolve base_url: explicit config > provider default
    base_url = config.base_url or defaults.get("base_url")

    # Resolve api_key: explicit config > provider env var > empty
    api_key = config.api_key
    if not api_key:
        env_var = defaults.get("env_var")
        if env_var:
            api_key = os.getenv(env_var, "")

    # For local provider with no key, use a dummy
    if not api_key and provider_enum == WhisperProvider.LOCAL:
        api_key = "not-needed"

    return OpenAICompatibleProvider(
        api_key=api_key,
        model=config.model,
        base_url=base_url,
        timeout=config.timeout,
        language=config.language,
        temperature=config.temperature,
        provider_name=config.provider,
        silence_threshold_dbfs=config.silence_threshold_dbfs,
        task=config.task,
    )
