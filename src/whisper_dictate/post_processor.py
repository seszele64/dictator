"""Prompt-driven post-processing via an OpenAI-compatible chat endpoint.

WHY THIS EXISTS: Post-processing sends a prompt (system message) and the raw
transcript (user message) to an OpenAI-compatible ``chat/completions`` endpoint
and returns the model's text. That is a different request/response contract
than audio transcription, so it gets its own module and error type instead of
overloading ``transcription.py``.

RESPONSIBILITY: Build a chat client from ``PostProcessConfig`` and run one
prompt/transcript completion.
BOUNDARIES:
- DOES: Resolve provider base URL and API key, construct the OpenAI client with
  the configured timeout, send the prompt/transcript pair, and return the
  trimmed first-choice content
- DOES NOT: Read ``WHISPER_*`` variables, consult the provider table's
  ``default_model`` (a transcription id), touch the database, clipboard, or
  notifications, or expose secrets in errors/logs

RELATIONSHIPS:
- USED BY: the ``process`` CLI command
- MIRRORS: ``create_transcriber()`` for provider/key/base-URL resolution
"""

import logging
import os

import openai
from openai import OpenAI

from whisper_dictate.config import (
    PROVIDER_DEFAULTS,
    PostProcessConfig,
    _resolve_provider_enum,
)

logger = logging.getLogger(__name__)


class PostProcessError(Exception):
    """WHY THIS EXISTS: Provider-specific SDK errors (``openai.APIError`` and
    friends) need to be wrapped so callers depend on one provider-agnostic
    failure type, mirroring ``TranscriptionError``.

    RESPONSIBILITY: Carry a short, user-facing failure message.
    BOUNDARIES:
    - DOES: Provide a stable error type for chat-processing failures
    - DOES NOT: Carry a traceback, the API key, or the transcript body
    """


def _failure_message(exc: Exception) -> str:
    """Map an SDK/transport exception to a short, secret-free user message.

    The message names the failure category only. It deliberately never embeds
    ``str(exc)`` for status errors (provider bodies can be large and are not
    part of our contract) and never includes the API key or the transcript.
    """
    if isinstance(exc, openai.AuthenticationError):
        return "Chat provider authentication failed. Check POST_PROCESS_API_KEY or the provider's API key."
    if isinstance(exc, openai.PermissionDeniedError):
        return "Chat provider denied the request. Check the API key's permissions."
    if isinstance(exc, openai.RateLimitError):
        return "Chat provider rate limit exceeded. Try again later."
    if isinstance(exc, openai.APITimeoutError):
        return "Chat request timed out. Increase POST_PROCESS_TIMEOUT or try again."
    if isinstance(exc, openai.APIConnectionError):
        return "Could not connect to the chat provider. Check POST_PROCESS_BASE_URL and your network."
    if isinstance(exc, openai.BadRequestError):
        return "Chat provider rejected the request. Check POST_PROCESS_MODEL and the transcript length."
    if isinstance(exc, openai.APIStatusError):
        return f"Chat provider returned an error (HTTP {exc.status_code})."
    if isinstance(exc, openai.APIError):
        return "Chat provider error."
    return f"Unexpected error while processing the transcript ({type(exc).__name__})."


class PostProcessor:
    """WHY THIS EXISTS: The CLI needs a small, mockable seam that owns exactly
    one chat completion, so tests can pin the request shape without a network.

    RESPONSIBILITY: Send the prompt/transcript pair and return trimmed content.
    BOUNDARIES:
    - DOES: Build the messages, call ``chat.completions.create``, validate and
      trim the response
    - DOES NOT: Resolve configuration, construct the client, or persist results

    RELATIONSHIPS:
    - CONSTRUCTED BY: create_post_processor()
    """

    def __init__(self, client: OpenAI, model: str) -> None:
        """Store the pre-built client and the already-stripped model.

        Args:
            client: An ``openai.OpenAI`` client (constructed with the resolved
                timeout by ``create_post_processor``).
            model: The stripped effective chat model.
        """
        self._client = client
        self._model = model

    @property
    def model(self) -> str:
        """The stripped effective model this processor will request."""
        return self._model

    def process(self, text: str, prompt: str) -> str:
        """Run one prompt/transcript completion.

        Args:
            text: The raw transcript, sent as the user message.
            prompt: The user's instruction, sent as the system message.

        Returns:
            str: The first choice's content with surrounding whitespace removed.

        Raises:
            PostProcessError: On any SDK/transport failure, a malformed
                response, or empty/whitespace-only content.
        """
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
            )
        except Exception as exc:
            raise PostProcessError(_failure_message(exc)) from exc

        stripped = self._extract_content(response).strip()
        if not stripped:
            raise PostProcessError("Chat provider returned an empty response.")
        return stripped

    @staticmethod
    def _extract_content(response: object) -> str:
        """Return the first choice's text content, or raise PostProcessError.

        A missing/empty ``choices`` list or a non-string ``content`` is treated
        as a provider failure rather than an ``IndexError``/``AttributeError``.
        """
        choices = getattr(response, "choices", None)
        if not choices:
            raise PostProcessError("Chat provider returned no choices.")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            raise PostProcessError("Chat provider returned an empty response.")
        return content


def create_post_processor(config: PostProcessConfig) -> PostProcessor:
    """WHY THIS EXISTS: The CLI should not know how to resolve provider facts or
    build an SDK client. This factory mirrors ``create_transcriber()`` so both
    resolution paths stay consistent.

    RESPONSIBILITY: Build a configured ``PostProcessor`` from chat config.
    BOUNDARIES:
    - DOES: Resolve the base URL and API key, strip the model, and construct
      ``openai.OpenAI(..., timeout=config.timeout)``
    - DOES NOT: Validate the config (that is ``validate_post_process_config``),
      call ``_resolve_model()``, or read ``PROVIDER_DEFAULTS[...]["default_model"]``

    The provider table is reused only for the shared ``base_url`` and
    ``env_var`` facts. ``default_model`` is a transcription id (``whisper-1``,
    ...) and is deliberately never consulted: the only model value used is
    ``config.model.strip()``.

    Args:
        config: Chat-processing configuration.

    Returns:
        PostProcessor: A processor bound to a client built with the resolved
        base URL, key, and ``config.timeout``.
    """
    provider_enum = _resolve_provider_enum(config.provider)
    defaults = PROVIDER_DEFAULTS[provider_enum]

    # Base URL: explicit override wins, else the provider default.
    base_url = config.base_url or defaults["base_url"]

    # API key: explicit wins, else the provider env var. Keyless providers
    # (local, custom) get the same dummy key create_transcriber() uses, because
    # the SDK refuses to construct a client with an empty key.
    api_key = config.api_key
    if not api_key:
        env_var = defaults["env_var"]
        if env_var:
            api_key = os.getenv(env_var, "")
    if not api_key and defaults["env_var"] is None:
        api_key = "not-needed"

    model = config.model.strip()

    # Log provider/model/timeout only — never the key, prompt, or transcript.
    logger.info(
        "Creating chat processor (provider=%s, model=%s, timeout=%s)",
        config.provider,
        model,
        config.timeout,
    )

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=config.timeout)
    return PostProcessor(client=client, model=model)
