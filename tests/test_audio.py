"""Tests for audio recording functionality."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_dictate.audio import AudioRecorder
from whisper_dictate.config import AudioConfig


class TestAudioRecorder:
    """Test the AudioRecorder class."""

    def test_init(self):
        """Test AudioRecorder initialization."""
        config = AudioConfig(sample_rate=16000, channels=1, duration=5.0, device=None)

        recorder = AudioRecorder(config)
        assert recorder.config == config

    def test_record_to_file_success(self):
        """Test successful audio recording to file."""
        config = AudioConfig(sample_rate=16000, channels=1, duration=1.0, device=None)

        recorder = AudioRecorder(config)

        with (
            patch("sounddevice.rec") as mock_rec,
            patch("sounddevice.wait") as mock_wait,
            patch("soundfile.write") as _mock_write,
            patch("tempfile.NamedTemporaryFile") as mock_temp,
        ):
            # Mock audio data
            mock_rec.return_value = [[0.1], [0.2], [0.3]]
            mock_wait.return_value = None

            # Mock temporary file
            mock_temp_file = Mock()
            mock_temp_file.name = "/tmp/test.wav"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            result = recorder.record_to_file()

            assert isinstance(result, Path)
            assert result == Path("/tmp/test.wav")

            # Verify recording parameters
            mock_rec.assert_called_once()
            rec_args = mock_rec.call_args
            assert rec_args[0][0] == 16000  # sample_rate * duration
            assert rec_args[1]["samplerate"] == 16000
            assert rec_args[1]["channels"] == 1
            assert rec_args[1]["dtype"] == "float32"

    def test_record_to_file_custom_duration(self):
        """Test recording with custom duration."""
        config = AudioConfig(sample_rate=16000, channels=1, duration=5.0, device=None)

        recorder = AudioRecorder(config)

        with (
            patch("sounddevice.rec") as mock_rec,
            patch("sounddevice.wait") as mock_wait,
            patch("soundfile.write") as _mock_write,
            patch("tempfile.NamedTemporaryFile") as mock_temp,
        ):
            mock_rec.return_value = [[0.1], [0.2], [0.3]]
            mock_wait.return_value = None

            mock_temp_file = Mock()
            mock_temp_file.name = "/tmp/test.wav"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            result = recorder.record_to_file(duration=2.5)

            assert isinstance(result, Path)

            # Verify custom duration was used
            mock_rec.assert_called_once()
            rec_args = mock_rec.call_args
            assert rec_args[0][0] == 40000  # 16000 * 2.5

    def test_record_to_file_with_device(self):
        """Test recording with specific device."""
        config = AudioConfig(
            sample_rate=16000, channels=1, duration=1.0, device="pulse"
        )

        recorder = AudioRecorder(config)

        with (
            patch("sounddevice.rec") as mock_rec,
            patch("sounddevice.wait") as mock_wait,
            patch("soundfile.write") as _mock_write,
            patch("tempfile.NamedTemporaryFile") as mock_temp,
        ):
            mock_rec.return_value = [[0.1], [0.2], [0.3]]
            mock_wait.return_value = None

            mock_temp_file = Mock()
            mock_temp_file.name = "/tmp/test.wav"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            result = recorder.record_to_file()

            assert isinstance(result, Path)

            # Verify device parameter
            rec_args = mock_rec.call_args
            assert rec_args[1]["device"] == "pulse"

    def test_record_to_file_portaudio_error(self):
        """Test handling of PortAudio errors."""
        config = AudioConfig(sample_rate=16000, channels=1, duration=1.0, device=None)

        recorder = AudioRecorder(config)

        with patch("sounddevice.rec") as mock_rec:
            from sounddevice import PortAudioError

            mock_rec.side_effect = PortAudioError("Device not found")

            with pytest.raises(PortAudioError, match="Device not found"):
                recorder.record_to_file()

    def test_record_to_file_soundfile_error(self):
        """Test handling of soundfile write errors."""
        config = AudioConfig(sample_rate=16000, channels=1, duration=1.0, device=None)

        recorder = AudioRecorder(config)

        with (
            patch("sounddevice.rec") as mock_rec,
            patch("sounddevice.wait") as mock_wait,
            patch("soundfile.write") as _mock_write,
            patch("tempfile.NamedTemporaryFile") as mock_temp,
        ):
            mock_rec.return_value = [[0.1], [0.2], [0.3]]
            mock_wait.return_value = None

            mock_temp_file = Mock()
            mock_temp_file.name = "/tmp/test.wav"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            _mock_write.side_effect = OSError("Cannot write file")

            with pytest.raises(IOError, match="Cannot write file"):
                recorder.record_to_file()

    def test_get_audio_devices(self):
        """Test getting available audio devices."""
        config = AudioConfig(sample_rate=16000, channels=1, duration=1.0, device=None)

        recorder = AudioRecorder(config)

        with patch("sounddevice.query_devices") as mock_query:
            mock_query.return_value = [
                {"name": "default", "max_input_channels": 2},
                {"name": "pulse", "max_input_channels": 2},
                {"name": "hw:0,0", "max_input_channels": 1},
                {"name": "hw:1,0", "max_input_channels": 0},  # Output only
            ]

            devices = recorder.get_audio_devices()

            assert devices == ("default", "pulse", "hw:0,0")
            mock_query.assert_called_once()

    def test_get_audio_devices_empty(self):
        """Test getting audio devices when none are available."""
        config = AudioConfig(sample_rate=16000, channels=1, duration=1.0, device=None)

        recorder = AudioRecorder(config)

        with patch("sounddevice.query_devices") as mock_query:
            mock_query.return_value = [
                {"name": "hw:0,0", "max_input_channels": 0},
                {"name": "hw:1,0", "max_input_channels": 0},
            ]

            devices = recorder.get_audio_devices()

            assert devices == ()

    def test_get_audio_devices_query_error(self):
        """Test handling of device query errors."""
        config = AudioConfig(sample_rate=16000, channels=1, duration=1.0, device=None)

        recorder = AudioRecorder(config)

        with patch("sounddevice.query_devices") as mock_query:
            from sounddevice import PortAudioError

            mock_query.side_effect = PortAudioError("Query failed")

            with pytest.raises(PortAudioError, match="Query failed"):
                recorder.get_audio_devices()

    def test_record_to_file_channels_config(self):
        """Test recording with different channel configurations."""
        config = AudioConfig(sample_rate=16000, channels=2, duration=1.0, device=None)

        recorder = AudioRecorder(config)

        with (
            patch("sounddevice.rec") as mock_rec,
            patch("sounddevice.wait") as mock_wait,
            patch("soundfile.write") as _mock_write,
            patch("tempfile.NamedTemporaryFile") as mock_temp,
        ):
            mock_rec.return_value = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
            mock_wait.return_value = None

            mock_temp_file = Mock()
            mock_temp_file.name = "/tmp/test.wav"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            result = recorder.record_to_file()

            assert isinstance(result, Path)

            # Verify channels parameter
            rec_args = mock_rec.call_args
            assert rec_args[1]["channels"] == 2
