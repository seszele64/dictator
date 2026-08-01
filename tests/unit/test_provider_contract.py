"""Tests for the transcription provider contract."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_dictate.config import WhisperConfig, WhisperProvider
from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider
from whisper_dictate.transcription import (
    TranscriptionError,
    TranscriptionProvider,
    TranscriptionResult,
    create_transcriber,
)


class TestTranscriptionResult:
    """Tests for the TranscriptionResult dataclass."""

    def test_init_defaults(self):
        """Defaults are set when only text is provided."""
        result = TranscriptionResult("hello")
        assert result.text == "hello"
        assert result.language is None
        assert result.duration is None
        assert result.provider is None
        assert result.silence_detected is False

    def test_init_all_fields(self):
        """All fields are stored when provided."""
        result = TranscriptionResult(
            text="hello",
            language="en",
            duration=3.5,
            provider="openai",
            silence_detected=True,
        )
        assert result.text == "hello"
        assert result.language == "en"
        assert result.duration == 3.5
        assert result.provider == "openai"
        assert result.silence_detected is True

    def test_str_returns_text(self):
        """str() returns the transcription text."""
        assert str(TranscriptionResult("hello")) == "hello"

    def test_repr_normal(self):
        """repr includes text (with truncation marker) and language."""
        result = TranscriptionResult("hello world", language="en")
        assert "TranscriptionResult(" in repr(result)
        assert "hello world" in repr(result)
        assert "..." in repr(result)
        assert "language=en" in repr(result)

    def test_repr_silence_detected(self):
        """repr reports silence_detected with empty text."""
        result = TranscriptionResult("", silence_detected=True, provider="openai")
        assert "silence_detected=True" in repr(result)
        assert "text=''" in repr(result)

    def test_repr_long_text_truncated(self):
        """repr truncates text longer than 50 characters."""
        long_text = "a" * 100
        result = TranscriptionResult(long_text)
        assert long_text[:50] in repr(result)
        assert "..." in repr(result)
        assert long_text not in repr(result)


class TestTranscriptionError:
    """Tests for the TranscriptionError exception."""

    def test_init_with_message(self):
        """Message is stored as the exception argument."""
        err = TranscriptionError("error msg")
        assert err.args[0] == "error msg"
        assert err.provider is None

    def test_init_with_provider(self):
        """Provider name is stored on the exception."""
        err = TranscriptionError("msg", provider="openai")
        assert err.provider == "openai"

    def test_is_exception(self):
        """TranscriptionError is an Exception subclass."""
        assert isinstance(TranscriptionError("msg"), Exception)

    def test_raises_and_catches(self):
        """TranscriptionError can be raised and caught by message."""
        with pytest.raises(TranscriptionError, match="msg"):
            raise TranscriptionError("msg")


class TestTranscriptionProviderABC:
    """Tests for the TranscriptionProvider abstract base class."""

    def test_cannot_instantiate_abc(self):
        """The abstract class cannot be instantiated directly."""
        with pytest.raises(TypeError):
            TranscriptionProvider()

    def test_has_provider_name_abstract(self):
        """provider_name is an abstract property."""
        assert "provider_name" in TranscriptionProvider.__abstractmethods__

    def test_has_transcribe_audio_abstract(self):
        """transcribe_audio is an abstract method."""
        assert "transcribe_audio" in TranscriptionProvider.__abstractmethods__


class TestOpenAICompatibleProvider:
    """Tests for OpenAICompatibleProvider construction and properties."""

    def test_init_defaults(self):
        """Defaults match the provider contract."""
        provider = OpenAICompatibleProvider(api_key="key")
        assert provider.provider_name == "openai"
        assert provider.model == "whisper-1"
        assert provider._language is None
        assert provider._temperature == 0.0
        assert provider._silence_threshold_dbfs == -50.0
        assert provider._task is None

    def test_init_custom_values(self):
        """Custom values are stored on the provider."""
        provider = OpenAICompatibleProvider(
            api_key="key",
            model="whisper-large-v3",
            base_url="https://api.groq.com/openai/v1",
            timeout=15.0,
            language="de",
            temperature=0.7,
            provider_name="groq",
            silence_threshold_dbfs=-60.0,
            task="translate",
        )
        assert provider.provider_name == "groq"
        assert provider.model == "whisper-large-v3"
        assert provider._language == "de"
        assert provider._temperature == 0.7
        assert provider._silence_threshold_dbfs == -60.0
        assert provider._task == "translate"
        assert provider._client.timeout == 15.0
        assert str(provider._client.base_url).startswith("https://api.groq.com/openai/v1")

    def test_provider_name_property(self):
        """provider_name property returns the stored name."""
        provider = OpenAICompatibleProvider(api_key="key", provider_name="groq")
        assert provider.provider_name == "groq"

    def test_model_property(self):
        """model property returns the stored model."""
        provider = OpenAICompatibleProvider(api_key="key", model="whisper-large-v3")
        assert provider.model == "whisper-large-v3"


class TestTranscribeAudio:
    """Tests for OpenAICompatibleProvider.transcribe_audio."""

    @staticmethod
    def _make_provider(**kwargs):
        """Build a provider with a mocked OpenAI client."""
        kwargs.setdefault("api_key", "test-key")
        provider = OpenAICompatibleProvider(**kwargs)
        provider._client = Mock()
        return provider

    def test_transcribe_file_not_found_raises_oserror(self):
        """Missing audio file raises OSError (not TranscriptionError)."""
        provider = OpenAICompatibleProvider(api_key="test-key")
        with pytest.raises(OSError):
            provider.transcribe_audio(Path("/nonexistent.wav"))

    def test_transcribe_success(self, temp_audio_file):
        """Successful transcription returns a populated result."""
        provider = self._make_provider()
        provider._client.audio.transcriptions.create.return_value = Mock(
            text="hello world", language="en"
        )
        with patch("whisper_dictate.audio_analysis.is_audio_silent", return_value=False):
            result = provider.transcribe_audio(temp_audio_file)
        assert result.text == "hello world"
        assert result.language == "en"
        assert result.provider == provider.provider_name
        assert result.silence_detected is False

    def test_transcribe_translates_when_task_translate(self, temp_audio_file):
        """task='translate' uses the translations API, not transcriptions."""
        provider = self._make_provider(task="translate")
        provider._client.audio.translations.create.return_value = Mock(
            text="bonjour", language="fr"
        )
        with patch("whisper_dictate.audio_analysis.is_audio_silent", return_value=False):
            result = provider.transcribe_audio(temp_audio_file)
        provider._client.audio.translations.create.assert_called_once()
        provider._client.audio.transcriptions.create.assert_not_called()
        assert result.text == "bonjour"

    def test_transcribe_transcribe_when_task_transcribe(self, temp_audio_file):
        """task='transcribe' uses the transcriptions API, not translations."""
        provider = self._make_provider(task="transcribe")
        provider._client.audio.transcriptions.create.return_value = Mock(
            text="hello", language="en"
        )
        with patch("whisper_dictate.audio_analysis.is_audio_silent", return_value=False):
            provider.transcribe_audio(temp_audio_file)
        provider._client.audio.transcriptions.create.assert_called_once()
        provider._client.audio.translations.create.assert_not_called()

    def test_transcribe_silence_detected_returns_empty(self, temp_audio_file):
        """Silent audio returns an empty result without calling the API."""
        provider = self._make_provider()
        with patch("whisper_dictate.audio_analysis.is_audio_silent", return_value=True):
            result = provider.transcribe_audio(temp_audio_file)
        assert result.text == ""
        assert result.silence_detected is True
        provider._client.audio.transcriptions.create.assert_not_called()

    def test_transcribe_silence_disabled_calls_api(self, temp_audio_file):
        """silence_threshold_dbfs=None skips silence detection and calls the API."""
        provider = self._make_provider(silence_threshold_dbfs=None)
        provider._client.audio.transcriptions.create.return_value = Mock(
            text="hello", language="en"
        )
        with patch("whisper_dictate.audio_analysis.is_audio_silent") as mock_silent:
            result = provider.transcribe_audio(temp_audio_file)
        mock_silent.assert_not_called()
        provider._client.audio.transcriptions.create.assert_called_once()
        assert result.text == "hello"

    def test_transcribe_error_wrapped(self, temp_audio_file):
        """Generic API exceptions are wrapped in TranscriptionError."""
        provider = self._make_provider(provider_name="openai")
        provider._client.audio.transcriptions.create.side_effect = Exception("API failed")
        with (
            patch("whisper_dictate.audio_analysis.is_audio_silent", return_value=False),
            pytest.raises(TranscriptionError) as excinfo,
        ):
            provider.transcribe_audio(temp_audio_file)
        assert "openai" in str(excinfo.value)
        assert "API failed" in str(excinfo.value)
        assert excinfo.value.provider == "openai"

    def test_transcribe_oserror_not_wrapped(self, temp_audio_file):
        """OSError propagates unwrapped."""
        provider = self._make_provider()
        provider._client.audio.transcriptions.create.side_effect = OSError("read error")
        with (
            patch("whisper_dictate.audio_analysis.is_audio_silent", return_value=False),
            pytest.raises(OSError, match="read error"),
        ):
            provider.transcribe_audio(temp_audio_file)

    def test_transcribe_forwards_params(self, temp_audio_file):
        """Model, temperature, language and response format are forwarded."""
        provider = self._make_provider(
            model="whisper-large-v3", language="fr", temperature=0.3
        )
        provider._client.audio.transcriptions.create.return_value = Mock(
            text="bonjour", language="fr"
        )
        with patch("whisper_dictate.audio_analysis.is_audio_silent", return_value=False):
            provider.transcribe_audio(temp_audio_file)
        kwargs = provider._client.audio.transcriptions.create.call_args.kwargs
        assert kwargs["model"] == "whisper-large-v3"
        assert kwargs["temperature"] == 0.3
        assert kwargs["language"] == "fr"
        assert kwargs["response_format"] == "json"


class TestCreateTranscriber:
    """Tests for the create_transcriber factory."""

    def test_create_transcriber_openai(self):
        """openai provider returns an OpenAICompatibleProvider."""
        provider = create_transcriber(WhisperConfig(provider="openai", api_key="test-key"))
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.provider_name == "openai"

    def test_create_transcriber_groq(self):
        """groq provider gets the Groq default base URL."""
        provider = create_transcriber(
            WhisperConfig(provider=WhisperProvider.GROQ.value, api_key="test-key")
        )
        assert isinstance(provider, OpenAICompatibleProvider)
        assert str(provider._client.base_url).startswith("https://api.groq.com/openai/v1")

    def test_create_transcriber_local_no_key(self):
        """local provider substitutes 'not-needed' as the API key."""
        provider = create_transcriber(WhisperConfig(provider="local"))
        assert provider._client.api_key == "not-needed"

    def test_create_transcriber_invalid_provider_falls_back(self):
        """Invalid provider falls back to the CUSTOM provider."""
        provider = create_transcriber(WhisperConfig(provider="invalid", api_key="test-key"))
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_create_transcriber_forwards_all_params(self):
        """All provider parameters are forwarded to the provider instance."""
        config = WhisperConfig(
            provider="groq",
            api_key="test-key",
            model="whisper-large-v3",
            base_url="https://custom.example.com/v1",
            timeout=15.0,
            language="fr",
            temperature=0.4,
            silence_threshold_dbfs=-40.0,
            task="translate",
        )
        provider = create_transcriber(config)
        assert provider.model == "whisper-large-v3"
        assert provider._language == "fr"
        assert provider._temperature == 0.4
        assert provider._silence_threshold_dbfs == -40.0
        assert provider._task == "translate"
        assert provider._client.timeout == 15.0
        assert str(provider._client.base_url).startswith("https://custom.example.com/v1")
