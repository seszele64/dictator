"""Tests for dictation workflow integration."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock, Mock

from whisper_dictate.dictation import DictationService


class TestDictationService:
    """Test the DictationService class."""

    def test_init(self, mock_config):
        """Test DictationService initialization."""
        with DictationService(mock_config) as service:
            assert service.config == mock_config
            assert service.audio_recorder is not None
            assert service.transcriber is not None
            assert service.clipboard is not None

    def test_dictate_success(self, mock_config, mock_transcription_result):
        """Test successful dictation workflow."""
        with DictationService(mock_config) as service:
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(
                    service.transcriber, "transcribe_audio"
                ) as mock_transcribe,
                patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
            ):
                # Mock successful operations
                mock_record.return_value = Path("/tmp/test.wav")
                mock_transcribe.return_value = mock_transcription_result
                mock_copy.return_value = True

                result = service.dictate()

                assert result is not None
                assert result.text == "This is a test transcription."
                assert result.language == "en"

                mock_record.assert_called_once()
                mock_transcribe.assert_called_once_with(Path("/tmp/test.wav"))
                mock_copy.assert_called_once_with("This is a test transcription.")

    def test_dictate_without_clipboard_copy(
        self, mock_config, mock_transcription_result
    ):
        """Test dictation without clipboard copying."""
        mock_config.copy_to_clipboard = False
        with DictationService(mock_config) as service:
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(
                    service.transcriber, "transcribe_audio"
                ) as mock_transcribe,
                patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
            ):
                mock_record.return_value = Path("/tmp/test.wav")
                mock_transcribe.return_value = mock_transcription_result

                result = service.dictate()

                assert result is not None
                assert result.text == "This is a test transcription."
                mock_copy.assert_not_called()

    def test_dictate_with_custom_duration(self, mock_config, mock_transcription_result):
        """Test dictation with custom duration."""
        with DictationService(mock_config) as service:
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(
                    service.transcriber, "transcribe_audio"
                ) as mock_transcribe,
                patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
            ):
                mock_record.return_value = Path("/tmp/test.wav")
                mock_transcribe.return_value = mock_transcription_result
                mock_copy.return_value = True

                result = service.dictate(duration=10.0)

                assert result is not None
                mock_record.assert_called_once_with(10.0)

    def test_dictate_recording_failure(self, mock_config):
        """Test handling of recording failures."""
        with DictationService(mock_config) as service:
            with patch.object(service.audio_recorder, "record_to_file") as mock_record:
                mock_record.side_effect = Exception("Recording failed")

                with pytest.raises(Exception, match="Recording failed"):
                    service.dictate()

    def test_dictate_transcription_failure(self, mock_config):
        """Test handling of transcription failures."""
        with DictationService(mock_config) as service:
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(
                    service.transcriber, "transcribe_audio"
                ) as mock_transcribe,
            ):
                mock_record.return_value = Path("/tmp/test.wav")
                mock_transcribe.side_effect = Exception("Transcription failed")

                with pytest.raises(Exception, match="Transcription failed"):
                    service.dictate()

    def test_dictate_clipboard_failure(self, mock_config, mock_transcription_result):
        """Test handling of clipboard failures (should not fail dictation)."""
        with DictationService(mock_config) as service:
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(
                    service.transcriber, "transcribe_audio"
                ) as mock_transcribe,
                patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                patch("os.unlink") as mock_unlink,
            ):
                mock_record.return_value = Path("/tmp/test.wav")
                mock_transcribe.return_value = mock_transcription_result
                mock_copy.return_value = False  # Clipboard copy fails
                mock_unlink.return_value = None

                result = service.dictate()

                assert result is not None
                assert result.text == "This is a test transcription."
                mock_copy.assert_called_once()

    def test_dictate_file_cleanup_on_success(
        self, mock_config, mock_transcription_result
    ):
        """Test that temporary files are cleaned up on success."""
        with DictationService(mock_config) as service:
            temp_file = Path("/tmp/test.wav")
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = PropertyMock(return_value=str(temp_file))
            mock_path.exists.return_value = True

            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(
                    service.transcriber, "transcribe_audio"
                ) as mock_transcribe,
                patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
            ):
                mock_record.return_value = mock_path
                mock_transcribe.return_value = mock_transcription_result
                mock_copy.return_value = True

                result = service.dictate()

                assert result is not None
                mock_path.unlink.assert_called_once()

    def test_dictate_file_cleanup_on_failure(self, mock_config):
        """Test that temporary files are cleaned up even on failure."""
        with DictationService(mock_config) as service:
            temp_file = Path("/tmp/test.wav")
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = PropertyMock(return_value=str(temp_file))
            mock_path.exists.return_value = True

            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(
                    service.transcriber, "transcribe_audio"
                ) as mock_transcribe,
            ):
                mock_record.return_value = mock_path
                mock_transcribe.side_effect = Exception("Transcription failed")

                with pytest.raises(Exception):
                    service.dictate()

                mock_path.unlink.assert_called_once()

    def test_dictate_file_cleanup_nonexistent_file(
        self, mock_config, mock_transcription_result
    ):
        """Test cleanup when file doesn't exist."""
        with DictationService(mock_config) as service:
            temp_file = Path("/tmp/nonexistent.wav")
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = PropertyMock(return_value=str(temp_file))
            mock_path.exists.return_value = True
            mock_path.unlink.side_effect = OSError("File not found")

            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(
                    service.transcriber, "transcribe_audio"
                ) as mock_transcribe,
                patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
            ):
                mock_record.return_value = mock_path
                mock_transcribe.return_value = mock_transcription_result
                mock_copy.return_value = True

                result = service.dictate()

                assert result is not None
                mock_path.unlink.assert_called_once()

    def test_get_system_info(self, mock_config):
        """Test system information gathering."""
        with DictationService(mock_config) as service:
            with (
                patch.object(
                    service.audio_recorder, "get_audio_devices"
                ) as mock_devices,
                patch.object(
                    service.clipboard,
                    "available_tools",
                    new_callable=lambda: ["xclip", "xsel"],
                ),
            ):
                mock_devices.return_value = ("default", "pulse")

                info = service.get_system_info()

                assert "audio_devices" in info
                assert "clipboard_tools" in info
                assert "config" in info

                assert info["audio_devices"] == ("default", "pulse")
                assert info["clipboard_tools"] == ["xclip", "xsel"]
                assert info["config"]["audio_sample_rate"] == 16000
                assert info["config"]["copy_to_clipboard"] is True
                assert info["config"]["openai_model"] == "whisper-1"

    def test_transcript_saved_with_recording_id(
        self, mock_config, mock_transcription_result
    ):
        """
        Test that transcripts are saved with correct recording_id.

        This is a regression test for the bug where recording_id was deleted
        from database state before transcription, causing transcripts to not
        be saved.
        """
        # Create mock database with properly configured methods
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()  # Mock for initialize
        mock_db.create_recording = Mock(return_value=42)  # recording_id = 42
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)

        # Need to also set up connection as a context manager and close
        mock_db.connection = Mock()
        mock_db.close = Mock()

        # Mock audio storage
        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (
            Path("/saved/test.wav"),
            "test.wav",
        )
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)

        # Create service after setting up mocks
        with (
            patch("whisper_dictate.dictation.get_database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.get_audio_storage",
                return_value=mock_audio_storage,
            ),
        ):
            with DictationService(mock_config) as service:
                with (
                    patch.object(
                        service.audio_recorder, "record_to_file"
                    ) as mock_record,
                    patch.object(
                        service.transcriber, "transcribe_audio"
                    ) as mock_transcribe,
                    patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                ):
                    # Setup mocks
                    mock_record.return_value = Path("/tmp/test.wav")
                    mock_transcribe.return_value = mock_transcription_result
                    mock_copy.return_value = True

                    # Execute dictation workflow
                    result = service.dictate()

                    # Verify result
                    assert result is not None
                    assert result.text == "This is a test transcription."

                    # Verify create_recording was called
                    mock_db.create_recording.assert_called_once()

                    # Verify create_transcript was called with the correct recording_id
                    mock_db.create_transcript.assert_called_once_with(
                        recording_id=42,
                        text="This is a test transcription.",
                        language="en",
                        model_used="whisper-1",
                        confidence=None,
                    )

                    # Verify the transcript is linked to the recording via recording_id
                    call_args = mock_db.create_transcript.call_args
                    assert call_args.kwargs["recording_id"] == 42


class TestDictationServiceMP3Integration:
    """Integration tests for MP3 transcription flow.

    Tests the complete flow:
    - Recording → Conversion → Transcription
    - MP3 disabled flow
    - WAV preservation flow
    """

    def test_dictate_mp3_enabled_converts_wav_to_mp3(
        self, mock_config_mp3_enabled, mock_transcription_result
    ):
        """Test that WAV is converted to MP3 when mp3_enabled=True."""
        # Mock database and audio storage
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=1)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()

        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (
            Path("/saved/test.mp3"),
            "test.mp3",
        )
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)

        with (
            patch("whisper_dictate.dictation.get_database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.get_audio_storage",
                return_value=mock_audio_storage,
            ),
        ):
            with DictationService(mock_config_mp3_enabled) as service:
                with (
                    patch.object(
                        service.audio_recorder, "record_to_file"
                    ) as mock_record,
                    patch.object(service.audio_converter, "convert") as mock_convert,
                    patch.object(
                        service.transcriber, "transcribe_audio"
                    ) as mock_transcribe,
                    patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                ):
                    # Setup mocks
                    wav_path = Path("/tmp/test_recording.wav")
                    mp3_path = Path("/tmp/test_recording.mp3")
                    mock_record.return_value = wav_path
                    mock_convert.return_value = mp3_path  # Conversion successful
                    mock_transcribe.return_value = mock_transcription_result
                    mock_copy.return_value = True

                    result = service.dictate()

                    # Verify result
                    assert result is not None
                    assert result.text == "This is a test transcription."

                    # Verify WAV was recorded
                    mock_record.assert_called_once()

                    # Verify conversion was called with correct delete_source setting
                    # keep_wav=False, so delete_source should be True
                    mock_convert.assert_called_once_with(wav_path, delete_source=True)

                    # Verify MP3 was sent to transcription
                    mock_transcribe.assert_called_once_with(mp3_path)

    def test_dictate_mp3_disabled_sends_wav_directly(
        self, mock_config, mock_transcription_result
    ):
        """Test that WAV is sent directly when mp3_enabled=False."""
        # Mock database and audio storage
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=1)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()

        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (
            Path("/saved/test.wav"),
            "test.wav",
        )
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)

        with (
            patch("whisper_dictate.dictation.get_database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.get_audio_storage",
                return_value=mock_audio_storage,
            ),
        ):
            with DictationService(mock_config) as service:
                with (
                    patch.object(
                        service.audio_recorder, "record_to_file"
                    ) as mock_record,
                    patch.object(service.audio_converter, "convert") as mock_convert,
                    patch.object(
                        service.transcriber, "transcribe_audio"
                    ) as mock_transcribe,
                    patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                ):
                    # Setup mocks
                    wav_path = Path("/tmp/test_recording.wav")
                    mock_record.return_value = wav_path
                    mock_convert.return_value = wav_path
                    mock_transcribe.return_value = mock_transcription_result
                    mock_copy.return_value = True

                    result = service.dictate()

                    # Verify result
                    assert result is not None
                    assert result.text == "This is a test transcription."

                    # Verify WAV was recorded
                    mock_record.assert_called_once()

                    # Verify conversion was NOT called (mp3_enabled=False)
                    mock_convert.assert_not_called()

                    # Verify WAV was sent directly to transcription
                    mock_transcribe.assert_called_once_with(wav_path)

    def test_dictate_mp3_enabled_keep_wav_preserves_original(
        self, mock_config_mp3_keep_wav, mock_transcription_result
    ):
        """Test that WAV is preserved when keep_wav=True."""
        # Mock database and audio storage
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=1)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()

        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (
            Path("/saved/test.mp3"),
            "test.mp3",
        )
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)

        with (
            patch("whisper_dictate.dictation.get_database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.get_audio_storage",
                return_value=mock_audio_storage,
            ),
        ):
            with DictationService(mock_config_mp3_keep_wav) as service:
                with (
                    patch.object(
                        service.audio_recorder, "record_to_file"
                    ) as mock_record,
                    patch.object(service.audio_converter, "convert") as mock_convert,
                    patch.object(
                        service.transcriber, "transcribe_audio"
                    ) as mock_transcribe,
                    patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                ):
                    # Setup mocks
                    wav_path = Path("/tmp/test_recording.wav")
                    mp3_path = Path("/tmp/test_recording.mp3")
                    mock_record.return_value = wav_path
                    mock_convert.return_value = mp3_path
                    mock_transcribe.return_value = mock_transcription_result
                    mock_copy.return_value = True

                    result = service.dictate()

                    # Verify result
                    assert result is not None
                    assert result.text == "This is a test transcription."

                    # Verify conversion was called with delete_source=False
                    # because keep_wav=True
                    mock_convert.assert_called_once_with(wav_path, delete_source=False)

                    # Verify MP3 was sent to transcription
                    mock_transcribe.assert_called_once_with(mp3_path)

    def test_dictate_mp3_fallback_to_wav_on_conversion_failure(
        self, mock_config_mp3_enabled, mock_transcription_result
    ):
        """Test that WAV is used when MP3 conversion fails."""
        # Mock database and audio storage
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=1)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()

        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (
            Path("/saved/test.wav"),
            "test.wav",
        )
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)

        with (
            patch("whisper_dictate.dictation.get_database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.get_audio_storage",
                return_value=mock_audio_storage,
            ),
        ):
            with DictationService(mock_config_mp3_enabled) as service:
                with (
                    patch.object(
                        service.audio_recorder, "record_to_file"
                    ) as mock_record,
                    patch.object(service.audio_converter, "convert") as mock_convert,
                    patch.object(
                        service.transcriber, "transcribe_audio"
                    ) as mock_transcribe,
                    patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                ):
                    # Setup mocks
                    wav_path = Path("/tmp/test_recording.wav")
                    mock_record.return_value = wav_path
                    # Conversion returns WAV when it fails (graceful fallback)
                    mock_convert.return_value = wav_path
                    mock_transcribe.return_value = mock_transcription_result
                    mock_copy.return_value = True

                    result = service.dictate()

                    # Verify result
                    assert result is not None
                    assert result.text == "This is a test transcription."

                    # Verify conversion was called
                    mock_convert.assert_called_once()

                    # Verify WAV was sent to transcription (fallback)
                    mock_transcribe.assert_called_once_with(wav_path)

    def test_dictate_records_correct_format_in_database(
        self, mock_config_mp3_enabled, mock_transcription_result
    ):
        """Test that the correct audio format is recorded in the database."""
        # Mock database and audio storage
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()

        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (
            Path("/saved/test.mp3"),
            "test.mp3",
        )
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)

        with (
            patch("whisper_dictate.dictation.get_database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.get_audio_storage",
                return_value=mock_audio_storage,
            ),
        ):
            with DictationService(mock_config_mp3_enabled) as service:
                with (
                    patch.object(
                        service.audio_recorder, "record_to_file"
                    ) as mock_record,
                    patch.object(service.audio_converter, "convert") as mock_convert,
                    patch.object(
                        service.transcriber, "transcribe_audio"
                    ) as mock_transcribe,
                    patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                ):
                    # Setup mocks
                    wav_path = Path("/tmp/test_recording.wav")
                    mp3_path = Path("/tmp/test_recording.mp3")
                    mock_record.return_value = wav_path
                    mock_convert.return_value = mp3_path
                    mock_transcribe.return_value = mock_transcription_result
                    mock_copy.return_value = True

                    result = service.dictate()

                    # Verify result
                    assert result is not None

                    # Verify create_recording was called with format='mp3'
                    mock_db.create_recording.assert_called_once()
                    call_kwargs = mock_db.create_recording.call_args.kwargs
                    assert call_kwargs["format"] == "mp3"
                    assert call_kwargs["duration"] == 1.0
                    assert call_kwargs["sample_rate"] == 16000
                    assert call_kwargs["channels"] == 1


class TestDictationServiceSilenceDetection:
    """Test silence detection behavior in DictationService."""

    def test_dictate_silent_skips_clipboard(self, mock_config, mock_silent_transcription_result):
        """Test that silent audio skips clipboard copy."""
        with DictationService(mock_config) as service:
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
                patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
            ):
                mock_record.return_value = Path("/tmp/test.wav")
                mock_transcribe.return_value = mock_silent_transcription_result
                
                result = service.dictate()
                
                # Should NOT copy to clipboard
                mock_copy.assert_not_called()
                assert result.silence_detected is True

    def test_dictate_silent_stores_empty_transcript(self, mock_config, mock_silent_transcription_result):
        """Test that silent audio stores empty transcript in database."""
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=1)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()
        
        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (Path("/saved/test.wav"), "test.wav")
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)
        
        with (
            patch("whisper_dictate.dictation.get_database", return_value=mock_db),
            patch("whisper_dictate.dictation.get_audio_storage", return_value=mock_audio_storage),
        ):
            with DictationService(mock_config) as service:
                with (
                    patch.object(service.audio_recorder, "record_to_file") as mock_record,
                    patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
                    patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                ):
                    mock_record.return_value = Path("/tmp/test.wav")
                    mock_transcribe.return_value = mock_silent_transcription_result
                    
                    result = service.dictate()
                    
                    # Should store empty transcript
                    mock_db.create_transcript.assert_called_once()
                    call_kwargs = mock_db.create_transcript.call_args.kwargs
                    assert call_kwargs["text"] == ""
                    
                    # Should NOT copy to clipboard
                    mock_copy.assert_not_called()

    def test_dictate_silent_logs_silence_detection(self, mock_config, mock_silent_transcription_result):
        """Test that silence detection is logged to database."""
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=1)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()
        
        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (Path("/saved/test.wav"), "test.wav")
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)
        
        with (
            patch("whisper_dictate.dictation.get_database", return_value=mock_db),
            patch("whisper_dictate.dictation.get_audio_storage", return_value=mock_audio_storage),
        ):
            with DictationService(mock_config) as service:
                with (
                    patch.object(service.audio_recorder, "record_to_file") as mock_record,
                    patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
                ):
                    mock_record.return_value = Path("/tmp/test.wav")
                    mock_transcribe.return_value = mock_silent_transcription_result
                    
                    result = service.dictate()
                    
                    # Should log silence detection
                    mock_db.create_log.assert_called()
                    log_call = mock_db.create_log.call_args
                    assert "Silence detected" in log_call.kwargs["message"]

    def test_dictate_non_silent_proceeds_normally(self, mock_config, mock_transcription_result):
        """Test that non-silent audio proceeds with normal workflow."""
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=1)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()
        
        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (Path("/saved/test.wav"), "test.wav")
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)
        
        with (
            patch("whisper_dictate.dictation.get_database", return_value=mock_db),
            patch("whisper_dictate.dictation.get_audio_storage", return_value=mock_audio_storage),
        ):
            with DictationService(mock_config) as service:
                with (
                    patch.object(service.audio_recorder, "record_to_file") as mock_record,
                    patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
                    patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                ):
                    mock_record.return_value = Path("/tmp/test.wav")
                    mock_transcribe.return_value = mock_transcription_result
                    mock_copy.return_value = True
                    
                    result = service.dictate()
                    
                    # Should copy to clipboard
                    mock_copy.assert_called_once_with("This is a test transcription.")
                    assert result.silence_detected is False
