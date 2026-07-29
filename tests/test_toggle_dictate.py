"""Tests for toggle_dictate module."""

from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

import toggle_dictate


class TestTranscribeAudio:
    """Test the transcribe_audio function."""

    def test_duration_calculated_and_saved(self):
        """Test that recording duration is calculated and saved to database.

        This is a regression test for the bug where recording duration was not
        calculated from the actual audio file using soundfile.info() after
        recording stops.
        """
        # Create mock config
        mock_config = MagicMock()
        mock_config.openai.model = "whisper-1"

        # Create mock database with properly configured sync methods
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.get_state = Mock(return_value=42)
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()
        mock_db.set_state = Mock()
        mock_db.delete_state = Mock()

        # Mock audio storage
        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (
            Path("/saved/test.wav"),
            "test.wav",
        )
        mock_audio_storage.recordings_path = Path("/recordings")

        # Create mock audio info that soundfile.info() will return
        mock_audio_info = Mock()
        mock_audio_info.duration = 5.0

        # Mock result from WhisperTranscriber
        mock_transcription_result = MagicMock()
        mock_transcription_result.text = "This is a test transcription."
        mock_transcription_result.language = "en"
        mock_transcription_result.silence_detected = False

        # Create mock Path object for AUDIO_FILE
        mock_audio_file = MagicMock(spec=Path)
        mock_audio_file.exists.return_value = True
        mock_audio_file.unlink.return_value = None

        with (
            patch.object(toggle_dictate, "get_db_and_storage") as mock_get_db_storage,
            patch(
                "toggle_dictate.sf.info", return_value=mock_audio_info
            ) as mock_sf_info,
            patch("toggle_dictate.create_transcriber") as mock_create_transcriber,
            patch("toggle_dictate.AUDIO_FILE", mock_audio_file),
            patch("toggle_dictate.ClipboardManager") as mock_clipboard_class,
        ):
            # Setup mocks
            mock_get_db_storage.return_value = (mock_db, mock_audio_storage)
            mock_transcriber_instance = MagicMock()
            mock_create_transcriber.return_value = mock_transcriber_instance
            mock_transcriber_instance.transcribe_audio.return_value = (
                mock_transcription_result
            )
            mock_clipboard_instance = MagicMock()
            mock_clipboard_class.return_value = mock_clipboard_instance

            # Call transcribe_audio
            result = toggle_dictate.transcribe_audio(mock_config, recording_id=42)

            # Verify result
            assert result == "This is a test transcription."

            # Verify db.execute was called with UPDATE to set duration
            mock_db.execute.assert_called()

            # Get the SQL query and parameters from the execute call
            call_args = mock_db.execute.call_args

            # Verify the call was made with duration 5.0
            assert call_args is not None
            args = call_args[0] if call_args[0] else ()
            kwargs = call_args[1] if len(call_args) > 1 else {}

            # Check that duration 5.0 is in the call arguments
            found_duration = (
                5.0 in args
                or kwargs.get("duration") == 5.0
                or any(
                    hasattr(arg, "__iter__") and 5.0 in arg
                    for arg in args
                    if not isinstance(arg, str)
                )
            )
            assert found_duration, (
                f"Expected duration 5.0 in execute call, got {call_args}"
            )

            # Verify soundfile.info was called
            mock_sf_info.assert_called_once()


class TestTranscribeAudioSilenceDetection:
    """Test silence detection behavior in toggle_dictate transcribe_audio."""

    def test_transcribe_silent_skips_clipboard(self):
        """Test that silent audio skips clipboard copy."""
        mock_config = MagicMock()
        mock_config.openai.model = "whisper-1"
        
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.get_state = Mock(return_value=42)
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()
        mock_db.set_state = Mock()
        mock_db.delete_state = Mock()
        
        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (Path("/saved/test.wav"), "test.wav")
        mock_audio_storage.recordings_path = Path("/recordings")
        
        mock_audio_info = Mock()
        mock_audio_info.duration = 5.0
        
        # Create silent result
        mock_silent_result = MagicMock()
        mock_silent_result.text = ""
        mock_silent_result.language = None
        mock_silent_result.silence_detected = True
        
        mock_audio_file = MagicMock(spec=Path)
        mock_audio_file.exists.return_value = True
        mock_audio_file.unlink.return_value = None
        
        with (
            patch.object(toggle_dictate, "get_db_and_storage") as mock_get_db_storage,
            patch("toggle_dictate.sf.info", return_value=mock_audio_info),
            patch("toggle_dictate.create_transcriber") as mock_create_transcriber,
            patch("toggle_dictate.AUDIO_FILE", mock_audio_file),
            patch("toggle_dictate.ClipboardManager") as mock_clipboard_class,
        ):
            mock_get_db_storage.return_value = (mock_db, mock_audio_storage)
            mock_transcriber_instance = MagicMock()
            mock_create_transcriber.return_value = mock_transcriber_instance
            mock_transcriber_instance.transcribe_audio.return_value = mock_silent_result
            mock_clipboard_instance = MagicMock()
            mock_clipboard_class.return_value = mock_clipboard_instance
            
            result = toggle_dictate.transcribe_audio(mock_config, recording_id=42)
            
            # Should NOT copy to clipboard
            mock_clipboard_instance.copy_to_clipboard.assert_not_called()
            
            # Should store empty transcript
            mock_db.create_transcript.assert_called()
            call_kwargs = mock_db.create_transcript.call_args.kwargs
            assert call_kwargs["text"] == ""

    def test_transcribe_non_silent_proceeds_normally(self):
        """Test that non-silent audio proceeds with normal workflow."""
        mock_config = MagicMock()
        mock_config.openai.model = "whisper-1"
        
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.get_state = Mock(return_value=42)
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()
        mock_db.set_state = Mock()
        mock_db.delete_state = Mock()
        
        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (Path("/saved/test.wav"), "test.wav")
        mock_audio_storage.recordings_path = Path("/recordings")
        
        mock_audio_info = Mock()
        mock_audio_info.duration = 5.0
        
        # Create normal result
        mock_normal_result = MagicMock()
        mock_normal_result.text = "Hello world"
        mock_normal_result.language = "en"
        mock_normal_result.silence_detected = False
        
        mock_audio_file = MagicMock(spec=Path)
        mock_audio_file.exists.return_value = True
        mock_audio_file.unlink.return_value = None
        
        with (
            patch.object(toggle_dictate, "get_db_and_storage") as mock_get_db_storage,
            patch("toggle_dictate.sf.info", return_value=mock_audio_info),
            patch("toggle_dictate.create_transcriber") as mock_create_transcriber,
            patch("toggle_dictate.AUDIO_FILE", mock_audio_file),
            patch("toggle_dictate.ClipboardManager") as mock_clipboard_class,
        ):
            mock_get_db_storage.return_value = (mock_db, mock_audio_storage)
            mock_transcriber_instance = MagicMock()
            mock_create_transcriber.return_value = mock_transcriber_instance
            mock_transcriber_instance.transcribe_audio.return_value = mock_normal_result
            mock_clipboard_instance = MagicMock()
            mock_clipboard_class.return_value = mock_clipboard_instance
            
            result = toggle_dictate.transcribe_audio(mock_config, recording_id=42)
            
            # Should copy to clipboard
            mock_clipboard_instance.copy_to_clipboard.assert_called_once_with("Hello world")
