"""Tests for transcription functionality."""

import pytest
from pathlib import Path
from unittest.mock import patch, Mock
from openai import APIError

from whisper_dictate.transcription import WhisperTranscriber, TranscriptionResult
from whisper_dictate.config import OpenAIConfig


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


class TestWhisperTranscriber:
    """Test the WhisperTranscriber class."""

    def test_init(self, mock_config, mock_openai_client):
        """Test WhisperTranscriber initialization."""
        transcriber = WhisperTranscriber(mock_config.openai, client=mock_openai_client)
        assert transcriber.config == mock_config.openai
        assert transcriber.client is not None

    def test_transcribe_audio_success(self, temp_audio_file, mock_openai_client):
        """Test successful audio transcription."""
        config = OpenAIConfig(api_key="test-key")
        transcriber = WhisperTranscriber(config, client=mock_openai_client)

        result = transcriber.transcribe_audio(temp_audio_file)

        assert isinstance(result, TranscriptionResult)
        assert result.text == "This is a test transcription."
        assert result.language == "en"

        # Verify API call
        mock_openai_client.audio.transcriptions.create.assert_called_once()
        call_args = mock_openai_client.audio.transcriptions.create.call_args
        assert call_args[1]["model"] == "whisper-1"
        assert call_args[1]["response_format"] == "json"

    def test_transcribe_audio_file_not_found(self, mock_openai_client):
        """Test transcription with non-existent file."""
        config = OpenAIConfig(api_key="test-key")
        transcriber = WhisperTranscriber(config, client=mock_openai_client)

        non_existent = Path("/non/existent/file.wav")

        with pytest.raises(IOError, match="Audio file not found"):
            transcriber.transcribe_audio(non_existent)

    def test_transcribe_audio_api_error(self, temp_audio_file, mock_openai_client):
        """Test handling of API errors."""
        config = OpenAIConfig(api_key="test-key")
        transcriber = WhisperTranscriber(config, client=mock_openai_client)

        # Mock API error
        mock_request = Mock()
        mock_openai_client.audio.transcriptions.create.side_effect = APIError(
            message="API Error", request=mock_request, body=None
        )

        with pytest.raises(APIError):
            transcriber.transcribe_audio(temp_audio_file)

    def test_transcribe_audio_unexpected_error(
        self, temp_audio_file, mock_openai_client
    ):
        """Test handling of unexpected errors."""
        config = OpenAIConfig(api_key="test-key")
        transcriber = WhisperTranscriber(config, client=mock_openai_client)

        # Mock unexpected error
        mock_openai_client.audio.transcriptions.create.side_effect = Exception(
            "Unexpected error"
        )

        with pytest.raises(Exception, match="Unexpected error"):
            transcriber.transcribe_audio(temp_audio_file)

    @patch("builtins.open", side_effect=IOError("Cannot read file"))
    def test_transcribe_audio_file_read_error(self, mock_file, mock_openai_client):
        """Test handling of file read errors."""
        config = OpenAIConfig(api_key="test-key")
        transcriber = WhisperTranscriber(config, client=mock_openai_client)

        # Create a mock file that exists but can't be read
        with patch("pathlib.Path.exists", return_value=True):
            audio_file = Path("test.wav")

            with pytest.raises(IOError, match="Cannot read file"):
                transcriber.transcribe_audio(audio_file)


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
            mock_create.return_value = mock_response
            
            result = provider.transcribe_audio(temp_audio_file)
            
            # Should have called API (silence detection disabled)
            mock_create.assert_called_once()
            assert result.text == "Hello world"
