"""Tests for audio silence detection functionality."""

import math
from pathlib import Path
from unittest.mock import patch

import numpy as np

from whisper_dictate.audio_analysis import is_audio_silent

# 1 s of 16 kHz mono samples — representative frame count for seam arrays.
N_SAMPLES = 16000


class TestIsAudioSilent:
    """Test the is_audio_silent function.

    The seam is the module-level soundfile binding of audio_analysis
    (``audio_analysis.sf``): each test patches ``sf.read`` to return a
    synthetic sample array. dBFS is 20*log10(rms) over ALL samples, so a
    constant array of amplitude A measures 20*log10(A) dBFS.
    """

    def test_silent_audio_below_threshold(self):
        """Test that audio below threshold is detected as silent."""
        # Amplitude 1e-4 -> -80 dBFS, far below the -50 dBFS threshold.
        mock_samples = np.full(N_SAMPLES, 1e-4, dtype=np.float32)

        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.return_value = (mock_samples, 16000)

            result = is_audio_silent(Path("/tmp/silent.wav"), threshold_dbfs=-50.0)

            assert result is True

    def test_noisy_audio_above_threshold(self):
        """Test that audio above threshold is detected as not silent."""
        # Amplitude 0.5 -> -9.0 dBFS (normal speech level), above -50.
        mock_samples = np.full(N_SAMPLES, 0.5, dtype=np.float32)

        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.return_value = (mock_samples, 16000)

            result = is_audio_silent(Path("/tmp/noisy.wav"), threshold_dbfs=-50.0)

            assert result is False

    def test_audio_at_threshold_not_silent(self):
        """Test that audio exactly at threshold is NOT silent (< not <=)."""
        # Amplitude 0.5 is exact in float32/float64 (0.5^2 = 0.25, mean and
        # sqrt introduce no rounding), so the module computes
        # dbfs = 20*log10(0.5) with zero drift. Using that exact float as the
        # threshold makes dbfs == threshold — the strict-< boundary itself.
        threshold = 20.0 * math.log10(0.5)
        mock_samples = np.full(N_SAMPLES, 0.5, dtype=np.float32)

        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.return_value = (mock_samples, 16000)

            result = is_audio_silent(Path("/tmp/threshold.wav"), threshold_dbfs=threshold)

            assert result is False  # < not <=

    def test_digital_silence_zeros_is_silent(self):
        """Test that all-zero samples (-inf dBFS) are detected as silent."""
        mock_samples = np.zeros(N_SAMPLES, dtype=np.float32)

        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.return_value = (mock_samples, 16000)

            result = is_audio_silent(Path("/tmp/zeros.wav"))

            assert result is True

    def test_fail_open_on_sf_read_error(self):
        """Test that soundfile errors return False (fail-open)."""
        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.side_effect = Exception("soundfile error")

            result = is_audio_silent(Path("/tmp/error.wav"))

            assert result is False  # Fail-open

    def test_fail_open_on_file_not_found(self):
        """Test that missing files return False (fail-open)."""
        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.side_effect = FileNotFoundError("File not found")

            result = is_audio_silent(Path("/tmp/missing.wav"))

            assert result is False

    def test_default_threshold(self):
        """Test that default threshold is -50.0 dBFS."""
        # Amplitude 0.001 -> ~-60 dBFS, below the default -50 threshold.
        mock_samples = np.full(N_SAMPLES, 0.001, dtype=np.float32)

        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.return_value = (mock_samples, 16000)

            # Use default threshold
            result = is_audio_silent(Path("/tmp/test.wav"))

            assert result is True

    def test_custom_threshold(self):
        """Test that custom threshold is respected."""
        # Amplitude 0.0056 -> ~-45.0 dBFS: below -40 but above -50.
        mock_samples = np.full(N_SAMPLES, 0.0056, dtype=np.float32)

        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.return_value = (mock_samples, 16000)

            # Custom threshold
            result = is_audio_silent(Path("/tmp/test.wav"), threshold_dbfs=-40.0)

            assert result is True

    def test_mp3_format_supported(self):
        """Test that MP3 files are supported."""
        mock_samples = np.full(N_SAMPLES, 0.001, dtype=np.float32)

        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.return_value = (mock_samples, 16000)

            result = is_audio_silent(Path("/tmp/test.mp3"))

            assert result is True
            # Seam pin: soundfile receives the path as a str (first positional
            # arg) with float32 normalization.
            mock_sf.read.assert_called_once_with("/tmp/test.mp3", dtype="float32")

    def test_wav_format_supported(self):
        """Test that WAV files are supported."""
        mock_samples = np.full(N_SAMPLES, 0.001, dtype=np.float32)

        with patch("whisper_dictate.audio_analysis.sf") as mock_sf:
            mock_sf.read.return_value = (mock_samples, 16000)

            result = is_audio_silent(Path("/tmp/test.wav"))

            assert result is True
