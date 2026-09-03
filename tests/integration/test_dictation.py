"""Tests for dictation workflow integration."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest

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
        with DictationService(mock_config) as service:  # noqa: SIM117
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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

    def test_dictate_without_clipboard_copy(self, mock_config, mock_transcription_result):
        """Test dictation without clipboard copying."""
        mock_config.copy_to_clipboard = False
        with DictationService(mock_config) as service:  # noqa: SIM117
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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
        with DictationService(mock_config) as service:  # noqa: SIM117
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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
        with DictationService(mock_config) as service:  # noqa: SIM117
            with patch.object(service.audio_recorder, "record_to_file") as mock_record:
                mock_record.side_effect = Exception("Recording failed")

                with pytest.raises(Exception, match="Recording failed"):
                    service.dictate()

    def test_dictate_transcription_failure(self, mock_config):
        """Test handling of transcription failures."""
        with DictationService(mock_config) as service:  # noqa: SIM117
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
            ):
                mock_record.return_value = Path("/tmp/test.wav")
                mock_transcribe.side_effect = Exception("Transcription failed")

                with pytest.raises(Exception, match="Transcription failed"):
                    service.dictate()

    def test_dictate_clipboard_failure(self, mock_config, mock_transcription_result):
        """Test handling of clipboard failures (should not fail dictation)."""
        with DictationService(mock_config) as service:  # noqa: SIM117
            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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

    def test_dictate_file_cleanup_on_success(self, mock_config, mock_transcription_result):
        """Test that temporary files are cleaned up on success."""
        with DictationService(mock_config) as service:
            temp_file = Path("/tmp/test.wav")
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = PropertyMock(return_value=str(temp_file))
            mock_path.exists.return_value = True

            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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
                patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
            ):
                mock_record.return_value = mock_path
                mock_transcribe.side_effect = RuntimeError("Transcription failed")

                with pytest.raises(RuntimeError):
                    service.dictate()

                mock_path.unlink.assert_called_once()

    def test_dictate_file_cleanup_nonexistent_file(self, mock_config, mock_transcription_result):
        """Test cleanup when file doesn't exist."""
        with DictationService(mock_config) as service:
            temp_file = Path("/tmp/nonexistent.wav")
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = PropertyMock(return_value=str(temp_file))
            mock_path.exists.return_value = True
            mock_path.unlink.side_effect = OSError("File not found")

            with (
                patch.object(service.audio_recorder, "record_to_file") as mock_record,
                patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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
        with (
            DictationService(mock_config) as service,
            patch.object(service.audio_recorder, "get_audio_devices") as mock_devices,
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

    def test_transcript_saved_with_recording_id(self, mock_config, mock_transcription_result):
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
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            DictationService(mock_config) as service,
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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

    def test_context_exit_closes_created_database(self, mock_config):
        """S2: leaving the service context closes the lazily created Database.

        The service must close the Database it created (and reset its
        reference) so a long-lived process never leaks the connection.
        """
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.connection = Mock()
        mock_db.close = Mock()

        with (
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch("whisper_dictate.dictation.AudioStorage"),
            DictationService(mock_config) as service,
        ):
            # Force lazy creation, mirroring the dictate() workflow
            assert service.database is mock_db
            mock_db.initialize.assert_called_once()
            mock_db.close.assert_not_called()

        # Leaving the context closes the database and forgets the reference
        mock_db.close.assert_called_once()
        assert service._db is None


class TestDictationServiceMP3Integration:
    """Integration tests for MP3 transcription flow.

    Tests the complete flow:
    - Recording → Conversion → Transcription
    - MP3 disabled flow
    - WAV preservation flow
    """

    def test_dictate_mp3_enabled_converts_wav_to_mp3(self, mock_config_mp3_enabled, mock_transcription_result):
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
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            DictationService(mock_config_mp3_enabled) as service,
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.audio_converter, "convert") as mock_convert,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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

    def test_dictate_mp3_disabled_sends_wav_directly(self, mock_config, mock_transcription_result):
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
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            DictationService(mock_config) as service,
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.audio_converter, "convert") as mock_convert,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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

    def test_dictate_mp3_enabled_keep_wav_preserves_original(self, mock_config_mp3_keep_wav, mock_transcription_result):
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
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            DictationService(mock_config_mp3_keep_wav) as service,
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.audio_converter, "convert") as mock_convert,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            DictationService(mock_config_mp3_enabled) as service,
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.audio_converter, "convert") as mock_convert,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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

    def test_dictate_records_correct_format_in_database(self, mock_config_mp3_enabled, mock_transcription_result):
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
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            DictationService(mock_config_mp3_enabled) as service,
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.audio_converter, "convert") as mock_convert,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
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
        with DictationService(mock_config) as service:  # noqa: SIM117
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

        with (  # noqa: SIM117
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch("whisper_dictate.dictation.AudioStorage", return_value=mock_audio_storage),
        ):
            with DictationService(mock_config) as service:
                with (
                    patch.object(service.audio_recorder, "record_to_file") as mock_record,
                    patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
                    patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
                ):
                    mock_record.return_value = Path("/tmp/test.wav")
                    mock_transcribe.return_value = mock_silent_transcription_result

                    service.dictate()

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

        with (  # noqa: SIM117
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch("whisper_dictate.dictation.AudioStorage", return_value=mock_audio_storage),
        ):
            with DictationService(mock_config) as service:
                with (
                    patch.object(service.audio_recorder, "record_to_file") as mock_record,
                    patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
                ):
                    mock_record.return_value = Path("/tmp/test.wav")
                    mock_transcribe.return_value = mock_silent_transcription_result

                    service.dictate()

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

        with (  # noqa: SIM117
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch("whisper_dictate.dictation.AudioStorage", return_value=mock_audio_storage),
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


class TestDictationFailureCleanup:
    """Failed/interrupted dictations must not leave ghost recording rows."""

    def _mock_db(self):
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.delete_recording = Mock(return_value=True)
        mock_db.close = Mock()
        return mock_db

    def _run_service(self, mock_config, mock_db, transcribe_side_effect):

        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (Path("/saved/test.wav"), "test.wav")
        mock_audio_storage.recordings_path = Path("/recordings")
        mock_audio_storage.check_disk_space.return_value = (True, 500)

        result_holder = {}

        with (
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            DictationService(mock_config) as service,
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
        ):
            mock_record.return_value = Path("/tmp/test.wav")
            mock_transcribe.side_effect = transcribe_side_effect
            try:
                result_holder["result"] = service.dictate()
            except BaseException as e:  # noqa: BLE001 - test re-raises below
                result_holder["raised"] = e

        return result_holder, mock_db

    def test_transcription_exception_removes_in_progress_row(self, mock_config):
        result, mock_db = self._run_service(mock_config, self._mock_db(), RuntimeError("Transcription failed"))
        assert isinstance(result.get("raised"), RuntimeError)
        mock_db.delete_recording.assert_called_once_with(42)

    def test_keyboard_interrupt_removes_in_progress_row(self, mock_config):
        result, mock_db = self._run_service(mock_config, self._mock_db(), KeyboardInterrupt())
        assert isinstance(result.get("raised"), KeyboardInterrupt)
        mock_db.delete_recording.assert_called_once_with(42)

    def test_success_keeps_row(self, mock_config, mock_transcription_result):
        result, mock_db = self._run_service(
            mock_config,
            self._mock_db(),
            lambda *a, **kw: mock_transcription_result,
        )
        assert result["result"] is not None
        mock_db.delete_recording.assert_not_called()

    def test_saved_recording_row_is_kept_on_late_failure(self, mock_config):
        """Once audio is persisted the row is kept (deleting would orphan the file)."""
        mock_db = MagicMock()
        mock_db.delete_recording = Mock(return_value=True)
        with (
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            DictationService(mock_config) as service,
        ):
            service._cleanup_failed_recording(42, recording_saved=True)
            assert mock_db.delete_recording.assert_not_called() is None
            service._cleanup_failed_recording(42, recording_saved=False)
            mock_db.delete_recording.assert_called_once_with(42)


class TestClaimFirstSaveOrdering:
    def test_file_path_claimed_before_finalize(self, mock_config, mock_transcription_result):
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.create_log = Mock(return_value=1)
        mock_db.close = Mock()

        order = []

        def db_claim(recording_id, file_path):
            order.append("claim")
            return True

        mock_db.update_recording_file_path = Mock(side_effect=db_claim)

        mock_audio_storage = MagicMock()
        mock_audio_storage.check_disk_space.return_value = (True, 500)

        def fake_finalize(staged):
            order.append("finalize")
            return Path("/saved/test.wav")

        mock_audio_storage.finalize_audio = Mock(side_effect=fake_finalize)

        with (
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            DictationService(mock_config) as service,
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
            patch.object(service.clipboard, "copy_to_clipboard"),
        ):
            mock_record.return_value = Path("/tmp/test.wav")
            mock_transcribe.return_value = mock_transcription_result
            service.dictate()

        assert "claim" in order and "finalize" in order
        assert order.index("claim") < order.index("finalize")

    def test_finalize_failure_rolls_back_claim_to_empty(self, mock_config, mock_transcription_result):
        """A finalize failure must clear the claimed file_path to ``""``.

        The rollback guarantees the row never points at a path that was
        never written (empty string is the "no file" sentinel).
        """
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.create_log = Mock(return_value=1)
        mock_db.close = Mock()
        mock_db.update_recording_file_path = Mock(return_value=True)

        mock_audio_storage = MagicMock()
        mock_audio_storage.check_disk_space.return_value = (True, 500)
        staged = Mock()
        staged.relative_path = Path("2026/09/session.wav")
        mock_audio_storage.stage_audio.return_value = staged
        mock_audio_storage.finalize_audio = Mock(side_effect=OSError("finalize failed"))

        with (
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            DictationService(mock_config) as service,
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
            patch.object(service.clipboard, "copy_to_clipboard"),
        ):
            mock_record.return_value = Path("/tmp/test.wav")
            mock_transcribe.return_value = mock_transcription_result
            # Save failure is warn-and-continue: dictate() still completes.
            assert service.dictate() is not None

        claim_calls = mock_db.update_recording_file_path.call_args_list
        assert list(claim_calls) == [
            ((42, "2026/09/session.wav"), {}),
            ((42, ""), {}),
        ], f"expected claim then rollback-to-empty, got {claim_calls}"


class TestKeepWavPersistence:
    """keep_wav=True must persist the WAV as the canonical file, never leak /tmp."""

    def test_keep_wav_persists_wav_and_unlinks_both_temps(
        self, mock_config_mp3_keep_wav, mock_transcription_result, tmp_path
    ):
        from whisper_dictate.config import DatabaseConfig

        recordings_root = tmp_path / "recordings"
        mock_config_mp3_keep_wav.database = DatabaseConfig(recordings_path=recordings_root)

        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.close = Mock()

        wav_tmp = tmp_path / "session.wav"
        wav_tmp.write_bytes(b"wav data")

        def fake_convert(wav_path, delete_source=None):
            mp3_path = wav_path.with_suffix(".mp3")
            mp3_path.write_bytes(b"mp3 data")
            assert delete_source is False  # keep_wav=True keeps the source
            return mp3_path

        with (
            DictationService(mock_config_mp3_keep_wav) as service,
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.audio_converter, "convert", side_effect=fake_convert),
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
        ):
            mock_record.return_value = wav_tmp
            mock_transcribe.return_value = mock_transcription_result

            result = service.dictate()

        assert result is not None

        # Exactly one persisted audio file, and it is the WAV
        persisted = [p for p in recordings_root.rglob("*") if p.is_file()]
        assert len(persisted) == 1
        assert persisted[0].suffix == ".wav"
        assert persisted[0].read_bytes() == b"wav data"

        # Row records the WAV format and the claimed relative path
        create_kwargs = mock_db.create_recording.call_args.kwargs
        assert create_kwargs["format"] == "wav"
        claim_calls = mock_db.update_recording_file_path.call_args_list
        assert any(str(c.args[1]).endswith(".wav") for c in claim_calls), (
            f"expected WAV relative path claim, got {claim_calls}"
        )

        # No temp files leaked: both the WAV and the transient MP3 are gone
        assert not wav_tmp.exists()
        assert not wav_tmp.with_suffix(".mp3").exists()
        assert not any(tmp_path.rglob(".staging-*"))

    def test_keep_wav_failure_leaves_no_temp_files(self, mock_config_mp3_keep_wav, tmp_path):
        from whisper_dictate.config import DatabaseConfig

        recordings_root = tmp_path / "recordings"
        mock_config_mp3_keep_wav.database = DatabaseConfig(recordings_path=recordings_root)

        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_recording = Mock(return_value=42)
        mock_db.execute = Mock()
        mock_db.delete_recording = Mock(return_value=True)
        mock_db.close = Mock()

        wav_tmp = tmp_path / "session.wav"
        wav_tmp.write_bytes(b"wav data")

        with (
            DictationService(mock_config_mp3_keep_wav) as service,
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch.object(service.audio_recorder, "record_to_file") as mock_record,
            patch.object(service.audio_converter, "convert") as mock_convert,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
        ):
            mock_record.return_value = wav_tmp
            mp3_tmp = wav_tmp.with_suffix(".mp3")
            mp3_tmp.write_bytes(b"mp3 data")
            mock_convert.return_value = mp3_tmp
            mock_transcribe.side_effect = RuntimeError("API down")

            with pytest.raises(RuntimeError):
                service.dictate()

        # Row cleaned up, nothing persisted, no temp files left behind
        mock_db.delete_recording.assert_called_once_with(42)
        assert not any(recordings_root.rglob("*")) or all(not p.is_file() for p in recordings_root.rglob("*"))
        assert not wav_tmp.exists()
        assert not mp3_tmp.exists()


class TestTranscribeExisting:
    """S4: DictationService.transcribe_existing — the toggle delegation seam.

    Parity contract with the former toggle.transcribe_audio: claim-first
    save (rollback on finalize failure), warn-and-continue on save failure,
    duration probe on the transcribed file, silence → empty transcript +
    no clipboard + no log row, transcript + clipboard otherwise, no
    create_log() rows ever, and in-progress row cleanup on failure.
    """

    AUDIO_FILE = Path("/tmp/audio.wav")
    STAGED_REL = "2026/09/session.wav"
    SAVED_PATH = Path("/recordings/2026/09/session.wav")

    def _run(
        self,
        mock_config,
        transcribe_return,
        recording_id=42,
        stage_error=None,
        finalize_error=None,
        transcribe_error=None,
        **call_kwargs,
    ):
        """Drive transcribe_existing with a mocked Database seam.

        Database/AudioStorage patches stay active for the whole call (the
        lazy properties construct on first access inside the flow).
        """
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.delete_recording = Mock(return_value=True)
        mock_db.close = Mock()
        mock_db.update_recording_file_path = Mock(return_value=True)
        mock_db.update_recording_duration = Mock(return_value=True)

        mock_audio_storage = MagicMock()
        staged = Mock()
        staged.relative_path = Path(self.STAGED_REL)
        mock_audio_storage.stage_audio.return_value = staged
        if stage_error is not None:
            mock_audio_storage.stage_audio.side_effect = stage_error
        mock_audio_storage.finalize_audio.return_value = self.SAVED_PATH
        if finalize_error is not None:
            mock_audio_storage.finalize_audio.side_effect = finalize_error

        audio_info = Mock()
        audio_info.duration = 5.0

        ctx = SimpleNamespace(db=mock_db, storage=mock_audio_storage)

        with (
            patch("whisper_dictate.dictation.Database", return_value=mock_db),
            patch(
                "whisper_dictate.dictation.AudioStorage",
                return_value=mock_audio_storage,
            ),
            patch("whisper_dictate.dictation.sf.info", return_value=audio_info),
            DictationService(mock_config) as service,
            patch.object(service.transcriber, "transcribe_audio") as mock_transcribe,
            patch.object(service.clipboard, "copy_to_clipboard") as mock_copy,
        ):
            mock_copy.return_value = True
            mock_transcribe.return_value = transcribe_return
            if transcribe_error is not None:
                mock_transcribe.side_effect = transcribe_error

            ctx.transcribe = mock_transcribe
            ctx.copy = mock_copy
            try:
                ctx.returned = service.transcribe_existing(recording_id, self.AUDIO_FILE, **call_kwargs)
            except BaseException as e:  # noqa: BLE001 - test re-asserts below
                ctx.raised = e

        return ctx

    def test_happy_path_claims_durations_transcribes_copies(self, mock_config, mock_transcription_result):
        """Non-silence: claim-first save, duration, transcript, clipboard."""
        ctx = self._run(mock_config, mock_transcription_result)

        assert ctx.returned is mock_transcription_result
        # Claim-first: exactly one claim with the staged relative path
        ctx.db.update_recording_file_path.assert_called_once_with(42, self.STAGED_REL)
        ctx.storage.finalize_audio.assert_called_once()
        # Duration probed on the SAVED file and written via the named method
        ctx.transcribe.assert_called_once_with(self.SAVED_PATH)
        ctx.db.update_recording_duration.assert_called_once_with(42, 5.0)
        # Transcript row + clipboard copy
        ctx.db.create_transcript.assert_called_once()
        assert ctx.db.create_transcript.call_args.kwargs["text"] == "This is a test transcription."
        ctx.copy.assert_called_once_with("This is a test transcription.")

    def test_silence_stores_empty_transcript_skips_clipboard(self, mock_config, mock_silent_transcription_result):
        """Silence: empty transcript row only - no clipboard, no log row."""
        ctx = self._run(mock_config, mock_silent_transcription_result)

        assert ctx.returned is mock_silent_transcription_result
        ctx.db.create_transcript.assert_called_once()
        assert ctx.db.create_transcript.call_args.kwargs["text"] == ""
        ctx.copy.assert_not_called()

    def test_save_failure_continues_with_source_file(self, mock_config, mock_transcription_result):
        """A stage failure warns, falls back to the source file, still stores."""
        ctx = self._run(mock_config, mock_transcription_result, stage_error=OSError("disk full"))

        assert ctx.returned is mock_transcription_result
        # The claim never happened and the rollback branch was not reached
        ctx.db.update_recording_file_path.assert_not_called()
        # Transcription used the original audio file
        ctx.transcribe.assert_called_once_with(self.AUDIO_FILE)
        # Transcript still stored and text still copied
        ctx.db.create_transcript.assert_called_once()
        ctx.copy.assert_called_once_with("This is a test transcription.")

    def test_finalize_failure_rolls_back_claim(self, mock_config, mock_transcription_result):
        """Finalize failure rolls the claim back to the empty sentinel."""
        ctx = self._run(
            mock_config,
            mock_transcription_result,
            finalize_error=OSError("finalize failed"),
        )

        assert ctx.returned is mock_transcription_result
        claims = ctx.db.update_recording_file_path.call_args_list
        assert [c.args for c in claims] == [(42, self.STAGED_REL), (42, "")]
        # Continued with the source file
        ctx.transcribe.assert_called_once_with(self.AUDIO_FILE)
        ctx.db.create_transcript.assert_called_once()

    def test_none_recording_id_skips_persistence_but_copies(self, mock_config, mock_transcription_result):
        """recording_id=None: no claim/duration/transcript, clipboard still runs."""
        ctx = self._run(mock_config, mock_transcription_result, recording_id=None)

        assert ctx.returned is mock_transcription_result
        ctx.db.update_recording_file_path.assert_not_called()
        ctx.db.update_recording_duration.assert_not_called()
        ctx.db.create_transcript.assert_not_called()
        ctx.copy.assert_called_once_with("This is a test transcription.")

    def test_failure_cleans_up_unpersisted_row(self, mock_config):
        """A failure with nothing persisted deletes the in-progress row.

        The save fails (warn-and-continue, audio_saved stays False) and the
        transcriber raises, so the row is still "in progress" and is removed.
        """
        ctx = self._run(
            mock_config,
            None,
            stage_error=OSError("disk full"),
            transcribe_error=RuntimeError("API down"),
        )

        assert isinstance(ctx.raised, RuntimeError)
        ctx.db.delete_recording.assert_called_once_with(42)

    def test_failure_keeps_row_once_audio_persisted(self, mock_config, mock_silent_transcription_result):
        """audio_saved=True keeps the row on a late failure (no orphaned file)."""
        ctx = self._run(
            mock_config,
            mock_silent_transcription_result,
            transcribe_error=RuntimeError("late boom"),
        )
        # The audio saved fine, so the failure cleanup must keep the row
        assert isinstance(ctx.raised, RuntimeError)
        ctx.db.delete_recording.assert_not_called()

    def test_copy_to_clipboard_false_honored(self, mock_config, mock_transcription_result):
        """copy_to_clipboard=False overrides the config-enabled default."""
        ctx = self._run(mock_config, mock_transcription_result, copy_to_clipboard=False)

        assert ctx.returned is mock_transcription_result
        ctx.copy.assert_not_called()
