"""WHY THIS EXISTS: Most Whisper API providers (OpenAI, Groq, Together AI,
local whisper.cpp servers) expose an OpenAI-compatible /v1/audio/transcriptions
endpoint. This single implementation works with all of them by accepting
configurable base_url and api_key parameters.

RESPONSIBILITY: Transcribe audio files using any OpenAI-compatible Whisper API.
BOUNDARIES:
- DOES: Make API calls to OpenAI-compatible endpoints and return structured results
- DOES NOT: Handle audio recording, file management, or clipboard operations

RELATIONSHIPS:
- IMPLEMENTS: TranscriptionProvider ABC from whisper_dictate.transcription
- USED BY: create_transcriber() factory function
- SUPPORTS: OpenAI, Groq, Together AI, local whisper.cpp, faster-whisper-server
"""

import logging
from pathlib import Path
from typing import Optional

import openai
from openai import OpenAI

from whisper_dictate.transcription import (
    TranscriptionError,
    TranscriptionProvider,
    TranscriptionResult,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(TranscriptionProvider):
    """WHY THIS EXISTS: Users need a single provider implementation that works
    with any OpenAI-compatible Whisper API endpoint, whether cloud-hosted
    (OpenAI, Groq, Together AI) or local (whisper.cpp, faster-whisper-server).

    RESPONSIBILITY: Transcribe audio files using the OpenAI Python SDK with
    configurable endpoint, authentication, and model parameters.
    BOUNDARIES:
    - DOES: Handle API calls, error wrapping, and result formatting
    - DOES NOT: Handle audio recording, file conversion, or configuration loading

    RELATIONSHIPS:
    - IMPLEMENTS: TranscriptionProvider ABC
    - DEPENDS ON: openai.OpenAI SDK client
    - USED BY: create_transcriber() factory function
    """

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        language: Optional[str] = None,
        temperature: float = 0.0,
        provider_name: str = "openai",
        silence_threshold_dbfs: Optional[float] = -50.0,
        task: Optional[str] = None,
    ) -> None:
        """Initialize OpenAI-compatible transcription provider.

        Args:
            api_key: API key for authentication (can be empty/dummy for local servers)
            model: Model name to use (e.g., "whisper-1", "whisper-large-v3")
            base_url: Custom API base URL. None uses OpenAI's default endpoint.
            timeout: Request timeout in seconds
            language: Language hint as ISO 639-1 code (e.g., "en", "de").
                     None means auto-detect.
            temperature: Sampling temperature (0.0 = deterministic)
            provider_name: Human-readable provider name for logging
            silence_threshold_dbfs: Pre-transcription silence detection threshold.
                                   None disables silence detection.
            task: Whisper task to perform (e.g., "transcribe", "translate").
                  None uses provider default.
        """
        self._provider_name = provider_name
        self._model = model
        self._language = language
        self._temperature = temperature
        self._silence_threshold_dbfs = silence_threshold_dbfs
        self._task = task

        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

    @property
    def provider_name(self) -> str:
        """Human-readable provider name for logging and diagnostics."""
        return self._provider_name

    @property
    def model(self) -> str:
        """Current model name (exposed for database logging)."""
        return self._model

    def transcribe_audio(self, audio_file: Path) -> TranscriptionResult:
        """WHY THIS EXISTS: Audio transcription needs to be handled consistently
        with proper error handling and result formatting across all providers.

        RESPONSIBILITY: Transcribe audio file using OpenAI-compatible API.
        BOUNDARIES:
        - DOES: Make API call, handle errors, and return structured result
        - DOES NOT: Handle file validation beyond existence check

        Args:
            audio_file: Path to audio file to transcribe

        Returns:
            TranscriptionResult: Structured transcription result

        Raises:
            IOError: If audio file cannot be read
            TranscriptionError: If API call fails
        """
        if not audio_file.exists():
            raise IOError(f"Audio file not found: {audio_file}")

        # Pre-transcription silence detection
        if self._silence_threshold_dbfs is not None:
            from whisper_dictate.audio_analysis import is_audio_silent
            if is_audio_silent(audio_file, self._silence_threshold_dbfs):
                logger.info(
                    f"Silence detected in {audio_file.name} "
                    f"(threshold={self._silence_threshold_dbfs} dBFS). "
                    f"Skipping transcription to prevent hallucination."
                )
                return TranscriptionResult(
                    text="",
                    silence_detected=True,
                    provider=self._provider_name,
                )

        logger.info(
            f"Transcribing with {self._provider_name}: {audio_file} "
            f"(model={self._model})"
        )

        try:
            with open(audio_file, "rb") as file:
                # Build extra parameters for providers like DeepInfra
                extra_params = {}
                if self._task:
                    extra_params["task"] = self._task

                response = self._client.audio.transcriptions.create(
                    model=self._model,
                    file=file,
                    response_format="json",
                    language=self._language,
                    temperature=self._temperature,
                    extra_body=extra_params if extra_params else None,
                )

            result = TranscriptionResult(
                text=response.text,
                language=getattr(response, "language", None),
                provider=self._provider_name,
            )

            logger.info(
                f"Transcription completed: {len(result.text)} characters, "
                f"language={result.language}"
            )

            return result

        except openai.APIError as e:
            logger.error(f"{self._provider_name} API error: {e}")
            raise TranscriptionError(str(e), provider=self._provider_name) from e
        except IOError:
            raise
        except Exception as e:
            logger.error(f"Unexpected transcription error: {e}")
            raise
