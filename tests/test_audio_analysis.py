"""Tests for audio silence detection functionality."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from whisper_dictate.audio_analysis import is_audio_silent


class TestIsAudioSilent:
    """Test the is_audio_silent function."""

    def test_silent_audio_below_threshold(self):
        """Test that audio below threshold is detected as silent."""
        # Mock pydub.AudioSegment with very low dBFS
        mock_audio = MagicMock()
        mock_audio.dBFS = -70.0  # Very silent
        
        with patch("pydub.AudioSegment") as mock_segment:
            mock_segment.from_file.return_value = mock_audio
            
            result = is_audio_silent(Path("/tmp/silent.wav"), threshold_dbfs=-50.0)
            
            assert result is True

    def test_noisy_audio_above_threshold(self):
        """Test that audio above threshold is detected as not silent."""
        mock_audio = MagicMock()
        mock_audio.dBFS = -30.0  # Normal speech level
        
        with patch("pydub.AudioSegment") as mock_segment:
            mock_segment.from_file.return_value = mock_audio
            
            result = is_audio_silent(Path("/tmp/noisy.wav"), threshold_dbfs=-50.0)
            
            assert result is False

    def test_audio_at_threshold_not_silent(self):
        """Test that audio exactly at threshold is NOT silent (< not <=)."""
        mock_audio = MagicMock()
        mock_audio.dBFS = -50.0  # Exactly at threshold
        
        with patch("pydub.AudioSegment") as mock_segment:
            mock_segment.from_file.return_value = mock_audio
            
            result = is_audio_silent(Path("/tmp/threshold.wav"), threshold_dbfs=-50.0)
            
            assert result is False  # < not <=

    def test_fail_open_on_pybub_error(self):
        """Test that pydub errors return False (fail-open)."""
        with patch("pydub.AudioSegment") as mock_segment:
            mock_segment.from_file.side_effect = Exception("pydub error")
            
            result = is_audio_silent(Path("/tmp/error.wav"))
            
            assert result is False  # Fail-open

    def test_fail_open_on_file_not_found(self):
        """Test that missing files return False (fail-open)."""
        with patch("pydub.AudioSegment") as mock_segment:
            mock_segment.from_file.side_effect = FileNotFoundError("File not found")
            
            result = is_audio_silent(Path("/tmp/missing.wav"))
            
            assert result is False

    def test_default_threshold(self):
        """Test that default threshold is -50.0 dBFS."""
        mock_audio = MagicMock()
        mock_audio.dBFS = -60.0  # Below default threshold
        
        with patch("pydub.AudioSegment") as mock_segment:
            mock_segment.from_file.return_value = mock_audio
            
            # Use default threshold
            result = is_audio_silent(Path("/tmp/test.wav"))
            
            assert result is True

    def test_custom_threshold(self):
        """Test that custom threshold is respected."""
        mock_audio = MagicMock()
        mock_audio.dBFS = -45.0  # Below -40 but above -50
        
        with patch("pydub.AudioSegment") as mock_segment:
            mock_segment.from_file.return_value = mock_audio
            
            # Custom threshold
            result = is_audio_silent(Path("/tmp/test.wav"), threshold_dbfs=-40.0)
            
            assert result is True

    def test_mp3_format_supported(self):
        """Test that MP3 files are supported."""
        mock_audio = MagicMock()
        mock_audio.dBFS = -60.0
        
        with patch("pydub.AudioSegment") as mock_segment:
            mock_segment.from_file.return_value = mock_audio
            
            result = is_audio_silent(Path("/tmp/test.mp3"))
            
            assert result is True
            mock_segment.from_file.assert_called_with(str(Path("/tmp/test.mp3")))

    def test_wav_format_supported(self):
        """Test that WAV files are supported."""
        mock_audio = MagicMock()
        mock_audio.dBFS = -60.0
        
        with patch("pydub.AudioSegment") as mock_segment:
            mock_segment.from_file.return_value = mock_audio
            
            result = is_audio_silent(Path("/tmp/test.wav"))
            
            assert result is True
