"""Tests for transcription functionality."""

from unittest.mock import Mock, patch

from whisper_dictate.transcription import TranscriptionResult


class TestTranscriptionResult:
    """Test the TranscriptionResult class."""

    def test_init(self):
        """Test TranscriptionResult initialization."""
        result = TranscriptionResult("Hello world", "en")
        assert result.text == "Hello world"
        assert result.language == "en"

    def test_init_without_language(self):
        """Test TranscriptionResult initialization without language."""
        result = TranscriptionResult("Hello world")
        assert result.text == "Hello world"
        assert result.language is None

    def test_str_representation(self):
        """Test string representation."""
        result = TranscriptionResult("Hello world")
        assert str(result) == "Hello world"

    def test_repr_representation(self):
        """Test repr representation."""
        result = TranscriptionResult("Hello world this is a long text")
        expected = "TranscriptionResult(text='Hello world this is a long text...', language=None)"
        assert repr(result) == expected


class TestOpenAICompatibleProvider:
    """Test silence detection integration in OpenAICompatibleProvider."""

    def test_transcribe_audio_silent_skips_api(self, temp_audio_file):
        """Test that silent audio skips API call entirely."""
        from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

        with patch("whisper_dictate.audio_analysis.is_audio_silent") as mock_silent:
            mock_silent.return_value = True  # Audio is silent

            provider = OpenAICompatibleProvider(
                api_key="test-key",
                silence_threshold_dbfs=-50.0,
            )

            result = provider.transcribe_audio(temp_audio_file)

            # Should NOT have called API
            assert result.text == ""
            assert result.silence_detected is True
            assert result.provider == "openai"

    def test_transcribe_audio_not_silent_calls_api(self, temp_audio_file, mock_openai_client):
        """Test that non-silent audio proceeds with API call."""
        from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

        with patch("whisper_dictate.audio_analysis.is_audio_silent") as mock_silent:
            mock_silent.return_value = False  # Audio is not silent

            provider = OpenAICompatibleProvider(
                api_key="test-key",
                silence_threshold_dbfs=-50.0,
            )

            # Inject mock client (provider creates its own in __init__,
            # so we replace it after construction)
            provider._client = mock_openai_client

            # Mock the API call
            mock_response = Mock()
            mock_response.text = "Hello world"
            mock_response.language = "en"
            mock_response.languages = ["en"]
            mock_openai_client.audio.transcriptions.create.return_value = mock_response

            result = provider.transcribe_audio(temp_audio_file)

            # Should have called API
            assert result.text == "Hello world"
            assert result.silence_detected is False

    def test_silence_detection_disabled_when_none(self, temp_audio_file):
        """Test that silence detection is disabled when threshold is None."""
        from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            api_key="test-key",
            silence_threshold_dbfs=None,
        )

        # Mock the API call to succeed
        with patch.object(provider._client.audio.transcriptions, "create") as mock_create:
            mock_response = Mock()
            mock_response.text = "Hello world"
            mock_response.language = "en"
            mock_response.languages = ["en"]
            mock_create.return_value = mock_response

            result = provider.transcribe_audio(temp_audio_file)

            # Should have called API (silence detection disabled)
            mock_create.assert_called_once()
            assert result.text == "Hello world"


class TestTranslateBranch:
    """Regression tests for the WHISPER_TASK=translate code path.

    The OpenAI SDK's audio.translations.create has NO `language` parameter
    (the endpoint always outputs English), so passing one breaks every
    translate call. The provider must omit the kwarg for translation while
    still passing it for transcription.
    """

    def test_translate_omits_language_kwarg(self, temp_audio_file, mock_openai_client):
        """task=translate must call translations.create without `language`."""
        from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            api_key="test-key",
            language="de",
            task="translate",
            silence_threshold_dbfs=None,
        )
        provider._client = mock_openai_client

        mock_response = Mock()
        mock_response.text = "Hola mundo"
        mock_response.language = "spanish"
        mock_response.languages = None
        mock_openai_client.audio.translations.create.return_value = mock_response

        result = provider.transcribe_audio(temp_audio_file)

        # Translations endpoint must NOT receive a language kwarg
        mock_openai_client.audio.translations.create.assert_called_once()
        call_kwargs = mock_openai_client.audio.translations.create.call_args.kwargs
        assert "language" not in call_kwargs
        # Remaining parameters are preserved
        assert call_kwargs["model"] == "whisper-1"
        assert call_kwargs["temperature"] == 0.0
        # Result is mapped from the response
        assert result.text == "Hola mundo"
        assert result.provider == "openai"

    def test_translate_without_language_hint(self, temp_audio_file, mock_openai_client):
        """task=translate with no configured language still omits the kwarg."""
        from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            api_key="test-key",
            language=None,
            task="translate",
            silence_threshold_dbfs=None,
        )
        provider._client = mock_openai_client

        mock_response = Mock()
        mock_response.text = "Hola mundo"
        mock_response.languages = None
        mock_openai_client.audio.translations.create.return_value = mock_response

        result = provider.transcribe_audio(temp_audio_file)

        call_kwargs = mock_openai_client.audio.translations.create.call_args.kwargs
        assert "language" not in call_kwargs
        assert result.text == "Hola mundo"

    def test_transcribe_passes_language_kwarg(self, temp_audio_file, mock_openai_client):
        """The transcribe branch must keep passing `language` unchanged."""
        from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            api_key="test-key",
            language="de",
            silence_threshold_dbfs=None,
        )
        provider._client = mock_openai_client

        mock_response = Mock()
        mock_response.text = "Hallo Welt"
        mock_response.language = "de"
        mock_response.languages = ["de"]
        mock_openai_client.audio.transcriptions.create.return_value = mock_response

        result = provider.transcribe_audio(temp_audio_file)

        mock_openai_client.audio.transcriptions.create.assert_called_once()
        call_kwargs = mock_openai_client.audio.transcriptions.create.call_args.kwargs
        assert call_kwargs["language"] == "de"
        assert result.text == "Hallo Welt"
