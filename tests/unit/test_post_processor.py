"""Unit tests for whisper_dictate.post_processor.

Group 3 of the post-process-prompt change: the chat processor and its factory.
The OpenAI client is mocked throughout — no network calls are made.
"""

import os
from unittest.mock import Mock, patch

import httpx
import openai
import pytest

from whisper_dictate.config import PostProcessConfig
from whisper_dictate.post_processor import (
    PostProcessError,
    PostProcessor,
    create_post_processor,
)


def _response(content: str | None) -> Mock:
    """Build a minimal chat-completions response object."""
    response = Mock()
    message = Mock()
    message.content = content
    choice = Mock()
    choice.message = message
    response.choices = [choice]
    return response


def _http_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.example.com/v1/chat/completions")


class TestPostProcessorProcess:
    """Request shape, trimming, and failure semantics of process()."""

    def test_sends_prompt_as_system_and_transcript_as_user(self):
        client = Mock()
        client.chat.completions.create.return_value = _response("ok")
        processor = PostProcessor(client=client, model="gpt-4o-mini")

        processor.process("hello world", "Translate to German")

        client.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Translate to German"},
                {"role": "user", "content": "hello world"},
            ],
        )

    def test_returns_trimmed_content(self):
        client = Mock()
        client.chat.completions.create.return_value = _response("  Hello world.  ")
        processor = PostProcessor(client=client, model="gpt-4o-mini")

        assert processor.process("text", "prompt") == "Hello world."

    def test_empty_content_is_a_failure(self):
        client = Mock()
        client.chat.completions.create.return_value = _response("   ")
        processor = PostProcessor(client=client, model="gpt-4o-mini")

        with pytest.raises(PostProcessError):
            processor.process("text", "prompt")

    def test_none_content_is_a_failure(self):
        client = Mock()
        client.chat.completions.create.return_value = _response(None)
        processor = PostProcessor(client=client, model="gpt-4o-mini")

        with pytest.raises(PostProcessError):
            processor.process("text", "prompt")

    def test_no_choices_is_a_failure(self):
        client = Mock()
        response = Mock()
        response.choices = []
        client.chat.completions.create.return_value = response
        processor = PostProcessor(client=client, model="gpt-4o-mini")

        with pytest.raises(PostProcessError):
            processor.process("text", "prompt")

    def test_model_property_exposes_stripped_model(self):
        processor = PostProcessor(client=Mock(), model="gpt-4o-mini")
        assert processor.model == "gpt-4o-mini"


class TestPostProcessorErrorWrapping:
    """SDK/transport failures become PostProcessError without leaking secrets."""

    def _processor_raising(self, exc: Exception) -> PostProcessor:
        client = Mock()
        client.chat.completions.create.side_effect = exc
        return PostProcessor(client=client, model="gpt-4o-mini")

    def test_authentication_error_is_wrapped_and_hides_key(self):
        secret = "sk-super-secret-value"
        exc = openai.AuthenticationError(
            f"Incorrect API key provided: {secret}",
            response=httpx.Response(401, request=_http_request()),
            body=None,
        )
        processor = self._processor_raising(exc)

        with pytest.raises(PostProcessError) as excinfo:
            processor.process("text", "prompt")

        message = str(excinfo.value)
        assert secret not in message
        assert "authentication" in message.lower()

    def test_timeout_error_is_wrapped(self):
        exc = openai.APITimeoutError(request=_http_request())
        processor = self._processor_raising(exc)

        with pytest.raises(PostProcessError, match="timed out"):
            processor.process("text", "prompt")

    def test_connection_error_is_wrapped(self):
        exc = openai.APIConnectionError(request=_http_request())
        processor = self._processor_raising(exc)

        with pytest.raises(PostProcessError, match="connect"):
            processor.process("text", "prompt")

    def test_status_error_is_wrapped_without_body(self):
        exc = openai.BadRequestError(
            "context length exceeded: <full transcript body>",
            response=httpx.Response(400, request=_http_request()),
            body=None,
        )
        processor = self._processor_raising(exc)

        with pytest.raises(PostProcessError) as excinfo:
            processor.process("text", "prompt")

        assert "<full transcript body>" not in str(excinfo.value)

    def test_unexpected_error_is_wrapped(self):
        processor = self._processor_raising(RuntimeError("boom"))

        with pytest.raises(PostProcessError):
            processor.process("text", "prompt")


class TestCreatePostProcessor:
    """Factory: base URL, key, model, and timeout resolution."""

    def test_openai_defaults_use_sdk_base_url_and_env_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        config = PostProcessConfig(provider="openai", model="gpt-4o-mini")

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(config)

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["api_key"] == "env-key"
        assert kwargs["base_url"] is None
        assert kwargs["timeout"] == 60.0

    def test_explicit_key_and_base_url_win(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        config = PostProcessConfig(
            provider="openai",
            model="gpt-4o-mini",
            api_key="explicit-key",
            base_url="https://custom.example.com/v1",
        )

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(config)

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["api_key"] == "explicit-key"
        assert kwargs["base_url"] == "https://custom.example.com/v1"

    def test_groq_uses_provider_base_url_and_env_key(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "groq-key")
        config = PostProcessConfig(provider="groq", model="llama-3.1-8b-instant")

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(config)

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["api_key"] == "groq-key"
        assert kwargs["base_url"] == "https://api.groq.com/openai/v1"

    def test_openrouter_uses_provider_base_url(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        config = PostProcessConfig(provider="openrouter", model="openai/gpt-4o-mini")

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(config)

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["base_url"] == "https://openrouter.ai/api/v1"

    def test_local_is_keyless_with_dummy_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config = PostProcessConfig(provider="local", model="local-model")

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(config)

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["api_key"] == "not-needed"
        assert kwargs["base_url"] == "http://localhost:8000/v1"

    def test_custom_uses_explicit_base_url_and_dummy_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config = PostProcessConfig(
            provider="custom",
            model="custom-model",
            base_url="https://my-endpoint.example.com/v1",
        )

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(config)

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["base_url"] == "https://my-endpoint.example.com/v1"
        assert kwargs["api_key"] == "not-needed"

    def test_timeout_default_and_override(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(PostProcessConfig(provider="openai", model="m"))
        assert mock_cls.call_args.kwargs["timeout"] == 60.0

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(PostProcessConfig(provider="openai", model="m", timeout=15.0))
        assert mock_cls.call_args.kwargs["timeout"] == 15.0

    def test_model_is_stripped_before_use(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        config = PostProcessConfig(provider="openai", model="  gpt-4o-mini  ")

        with patch("whisper_dictate.post_processor.OpenAI"):
            processor = create_post_processor(config)

        assert processor.model == "gpt-4o-mini"

    def test_whisper_api_key_is_never_read(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("WHISPER_API_KEY", "whisper-secret")
        config = PostProcessConfig(provider="openai", model="gpt-4o-mini")

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(config)

        assert mock_cls.call_args.kwargs["api_key"] == ""

    def test_provider_default_model_is_never_consulted(self, monkeypatch):
        """The provider table's transcription default_model must never leak in."""
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        config = PostProcessConfig(provider="openai", model="chat-model")

        with (
            patch("whisper_dictate.post_processor.OpenAI"),
            patch(
                "whisper_dictate.post_processor.PROVIDER_DEFAULTS",
                {"openai": {"base_url": None, "env_var": "OPENAI_API_KEY", "default_model": "SHOULD-NOT-BE-USED"}},
            ),
        ):
            processor = create_post_processor(config)

        assert processor.model == "chat-model"

    def test_no_whisper_env_var_reaches_the_client(self, monkeypatch):
        for key in list(os.environ):
            if key.startswith("WHISPER_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("WHISPER_BASE_URL", "https://whisper.example.com/v1")
        monkeypatch.setenv("WHISPER_TIMEOUT", "1")
        config = PostProcessConfig(provider="local", model="m")

        with patch("whisper_dictate.post_processor.OpenAI") as mock_cls:
            create_post_processor(config)

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["base_url"] == "http://localhost:8000/v1"
        assert kwargs["timeout"] == 60.0
