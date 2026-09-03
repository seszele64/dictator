"""WHY THIS EXISTS: Whisper transcription providers need to be organized
in a dedicated package so that new provider implementations can be added
without modifying core transcription logic.

RESPONSIBILITY: Re-export provider implementations for easy importing.
BOUNDARIES:
- DOES: Provide convenient imports for provider classes
- DOES NOT: Implement provider logic or configuration
"""

from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

__all__ = ["OpenAICompatibleProvider"]
