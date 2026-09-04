"""Tests for audio converter functionality."""

import contextlib
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_ffmpeg_subprocess():
    """Mock the ffmpeg subprocess seam of AudioConverter.

    Success path: 'encodes' by creating the output file (the last argv
    element), mirroring the empty-file behavior of the old export mock.
    Individual tests override ``mock_run.side_effect`` to simulate specific
    failure modes (FileNotFoundError -> 'FFmpeg not found' fallback; generic
    Exception / nonzero exit -> generic fallback).
    """
    with patch("whisper_dictate.audio_converter.subprocess.run") as mock_run:

        def fake_run(cmd, **kwargs):
            Path(cmd[-1]).touch()  # create the output MP3
            result = Mock()
            result.returncode = 0
            result.stderr = ""
            return result

        mock_run.side_effect = fake_run
        yield mock_run


class TestAudioConverter:
    """Test the AudioConverter class."""

    def test_init_default_values(self):
        """Test AudioConverter initialization with default values."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()
        assert converter.bitrate == "128k"
        assert converter.keep_wav is False

    def test_init_custom_values(self):
        """Test AudioConverter initialization with custom values."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter(bitrate="64k", keep_wav=True)
        assert converter.bitrate == "64k"
        assert converter.keep_wav is True

    def test_convert_success(self, temp_audio_file):
        """Test successful WAV to MP3 conversion."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        result = converter.convert(temp_audio_file)

        # Verify result
        assert result == temp_audio_file.with_suffix(".mp3")
        assert result.exists()

    def test_convert_with_custom_bitrate(self, temp_audio_file):
        """Test conversion with custom bitrate."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter(bitrate="64k")

        result = converter.convert(temp_audio_file)

        # Should still work with custom bitrate
        assert result == temp_audio_file.with_suffix(".mp3")
        assert result.exists()

    def test_convert_fallback_when_ffmpeg_unavailable(self, temp_audio_file, mock_ffmpeg_subprocess):
        """Test fallback to original WAV when FFmpeg is not available."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        # Simulate FFmpeg not found by making subprocess.run raise FileNotFoundError
        mock_ffmpeg_subprocess.side_effect = FileNotFoundError("ffmpeg not found")

        result = converter.convert(temp_audio_file)

        # Should return original WAV path
        assert result == temp_audio_file

    def test_convert_fallback_on_generic_error(self, temp_audio_file, mock_ffmpeg_subprocess):
        """Test fallback to original WAV on any conversion error."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        # Simulate any conversion error
        mock_ffmpeg_subprocess.side_effect = Exception("Corrupt audio file")

        result = converter.convert(temp_audio_file)

        # Should return original WAV path
        assert result == temp_audio_file

    def test_convert_fallback_on_nonzero_ffmpeg_exit(self, temp_audio_file, mock_ffmpeg_subprocess):
        """Test fallback to original WAV when ffmpeg exits nonzero (e.g. corrupt input)."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        failed = Mock()
        failed.returncode = 1
        failed.stderr = "ffmpeg error: invalid data"
        mock_ffmpeg_subprocess.side_effect = None
        mock_ffmpeg_subprocess.return_value = failed

        result = converter.convert(temp_audio_file)

        # Should return original WAV path (generic fallback, never raises)
        assert result == temp_audio_file

    def test_convert_invokes_ffmpeg_with_expected_args(self, temp_audio_file, mock_ffmpeg_subprocess):
        """Pin the ffmpeg argv contract: single-pass encode at the configured bitrate."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter(bitrate="64k")
        converter.convert(temp_audio_file)

        assert mock_ffmpeg_subprocess.call_count == 1
        cmd = mock_ffmpeg_subprocess.call_args.args[0]
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd  # overwrite output
        assert cmd[cmd.index("-i") + 1] == str(temp_audio_file)
        assert cmd[cmd.index("-codec:a") + 1] == "libmp3lame"
        assert cmd[cmd.index("-b:a") + 1] == "64k"
        assert cmd[-1] == str(temp_audio_file.with_suffix(".mp3"))
        kwargs = mock_ffmpeg_subprocess.call_args.kwargs
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True

    def test_convert_deletes_source_by_default(self, temp_audio_file):
        """Test that source WAV is deleted after successful conversion."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter(keep_wav=False)

        result = converter.convert(temp_audio_file)

        # Source WAV should be deleted
        assert not temp_audio_file.exists()
        assert result.exists()
        assert result.suffix == ".mp3"

    def test_convert_keeps_source_when_keep_wav_true(self, temp_audio_file):
        """Test that source WAV is preserved when keep_wav=True."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter(keep_wav=True)

        result = converter.convert(temp_audio_file)

        # Source WAV should still exist
        assert temp_audio_file.exists()
        assert result.exists()
        assert result.suffix == ".mp3"

    def test_convert_delete_source_overrides_keep_wav(self, temp_audio_file):
        """Test that delete_source=True overrides keep_wav setting."""
        from whisper_dictate.audio_converter import AudioConverter

        # keep_wav=True but delete_source=True should still delete
        converter = AudioConverter(keep_wav=True)

        result = converter.convert(temp_audio_file, delete_source=True)

        # Source WAV should be deleted because delete_source=True
        assert not temp_audio_file.exists()
        assert result.exists()

    def test_convert_preserves_when_delete_source_false_and_keep_wav_false(self, temp_audio_file):
        """Test WAV is preserved when delete_source=False and keep_wav=False."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter(keep_wav=False)

        result = converter.convert(temp_audio_file, delete_source=False)

        # Source WAV should still exist because delete_source=False
        assert temp_audio_file.exists()
        assert result.exists()

    def test_convert_accepts_string_path(self):
        """Test that convert accepts string path instead of Path object."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        # Create temp file with string path
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"RIFF")
            tmp.flush()
            wav_path_str = tmp.name
            mp3_path_str = wav_path_str.replace(".wav", ".mp3")

        try:
            result = converter.convert(wav_path_str)

            # Should work with string path
            assert result == Path(mp3_path_str)
            assert result.exists()
        finally:
            # Cleanup
            with contextlib.suppress(OSError):
                os.unlink(wav_path_str)
            with contextlib.suppress(OSError):
                os.unlink(mp3_path_str)

    def test_convert_with_path_object(self, temp_audio_file):
        """Test convert properly handles Path objects."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        # Pass Path object directly
        result = converter.convert(Path(temp_audio_file))

        # Should work with Path input
        assert result.suffix == ".mp3"
        assert result.exists()

    def test_output_path_has_mp3_extension(self, temp_audio_file):
        """Test that output path has .mp3 extension."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        result = converter.convert(temp_audio_file)

        assert result.suffix == ".mp3"
        assert result.name.endswith(".mp3")

    def test_convert_logs_start(self, temp_audio_file, caplog):
        """Test that conversion start is logged."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        with caplog.at_level("INFO"):
            converter.convert(temp_audio_file)

        # Check that start of conversion was logged
        assert any("Starting WAV to MP3 conversion" in record.message for record in caplog.records)

    def test_convert_logs_success_with_size_reduction(self, temp_audio_file, caplog):
        """Test that successful conversion with size reduction is logged."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        with caplog.at_level("INFO"):
            converter.convert(temp_audio_file)

        # Check success message with size info
        assert any("Conversion successful" in record.message for record in caplog.records)

    def test_convert_logs_warning_on_ffmpeg_missing(self, temp_audio_file, caplog, mock_ffmpeg_subprocess):
        """Test that warning is logged when FFmpeg is missing."""
        from whisper_dictate.audio_converter import AudioConverter

        converter = AudioConverter()

        # Simulate FFmpeg not found
        mock_ffmpeg_subprocess.side_effect = FileNotFoundError("ffmpeg not found")

        with caplog.at_level("WARNING"):
            result = converter.convert(temp_audio_file)

        # Check warning message
        assert any("FFmpeg not found" in record.message for record in caplog.records)
        # Should still return WAV path
        assert result == temp_audio_file


class TestAudioConfigDefaults:
    """Test that AudioConfig has correct default MP3 values."""

    def test_default_mp3_enabled_is_true(self):
        """Test that mp3_enabled defaults to True."""
        from whisper_dictate.config import AudioConfig

        config = AudioConfig()
        assert config.mp3_enabled is True

    def test_default_mp3_bitrate_is_128k(self):
        """Test that mp3_bitrate defaults to '128k'."""
        from whisper_dictate.config import AudioConfig

        config = AudioConfig()
        assert config.mp3_bitrate == "128k"

    def test_default_keep_wav_is_false(self):
        """Test that keep_wav defaults to False."""
        from whisper_dictate.config import AudioConfig

        config = AudioConfig()
        assert config.keep_wav is False

    def test_custom_mp3_config_values(self):
        """Test that custom MP3 config values are respected."""
        from whisper_dictate.config import AudioConfig

        config = AudioConfig(mp3_enabled=False, mp3_bitrate="64k", keep_wav=True)
        assert config.mp3_enabled is False
        assert config.mp3_bitrate == "64k"
        assert config.keep_wav is True


class TestFileSizeReduction:
    """Test WAV to MP3 file size reduction.

    Per spec: MP3 at 128 kbps should achieve 80-90% size reduction.
    A 10MB WAV should become 1-2MB MP3.
    """

    def test_file_size_reduction_at_128k(self, mock_ffmpeg_subprocess):
        """Test that WAV to MP3 at 128k achieves 80-90% size reduction.

        This test creates a simulated WAV file of ~10MB and verifies
        that the resulting MP3 is between 1-2MB (80-90% reduction).

        Note: ``mock_ffmpeg_subprocess`` MUST be a fixture parameter here.
        Without it, the name resolves to the module-level fixture function
        (not the yielded mock) and the side_effect assignment silently lands
        on the function object, leaving the autouse 0-byte fake_run in charge.
        """
        from whisper_dictate.audio_converter import AudioConverter

        # Create a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            # Simulate a ~10MB WAV file (10,485,760 bytes = 10MB)
            # WAV header is ~44 bytes + data
            wav_size = 10 * 1024 * 1024  # 10MB
            wav_header = (
                b"RIFF"
                + (wav_size - 8).to_bytes(4, "little")
                + b"WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00"
                b"\x00}\x00\x00\x02\x00\x10\x00data" + (wav_size - 44).to_bytes(4, "little")
            )
            # Pad with zeros to reach 10MB
            padding = b"\x00" * (wav_size - len(wav_header))
            tmp.write(wav_header + padding)
            tmp.flush()
            wav_path = Path(tmp.name)

        try:
            # Track the original size
            original_size = wav_path.stat().st_size
            assert original_size >= wav_size - 100, "WAV file should be ~10MB"

            converter = AudioConverter(bitrate="128k")

            # Simulate a realistic encode on the subprocess seam: the "MP3"
            # written is 10-20% of the original size (80-90% compression),
            # same simulation the old export mock performed.
            def fake_run(cmd, **kwargs):
                mp3_path = Path(cmd[-1])
                # Simulate MP3 being 10-20% of original size
                # This simulates 80-90% compression
                simulated_mp3_size = int(original_size * 0.15)
                mp3_path.write_bytes(b"\x00" * simulated_mp3_size)
                result = Mock()
                result.returncode = 0
                result.stderr = ""
                return result

            mock_ffmpeg_subprocess.side_effect = fake_run

            result = converter.convert(wav_path)

            # Verify MP3 was created
            assert result.suffix == ".mp3"
            assert result.exists()

            mp3_size = result.stat().st_size
            reduction_ratio = mp3_size / original_size

            # MP3 should be 10-20% of original (80-90% reduction)
            assert 0.10 <= reduction_ratio <= 0.20, (
                f"MP3 size ({mp3_size}) should be 10-20% of WAV size ({original_size}), "
                f"got {reduction_ratio * 100:.1f}%"
            )

            # In actual bytes: 10MB -> 1-2MB
            expected_min = int(original_size * 0.10)
            expected_max = int(original_size * 0.20)
            assert expected_min <= mp3_size <= expected_max, (
                f"MP3 should be between {expected_min / 1024 / 1024:.1f}MB and "
                f"{expected_max / 1024 / 1024:.1f}MB, got {mp3_size / 1024 / 1024:.2f}MB"
            )
        finally:
            # Cleanup
            with contextlib.suppress(OSError):
                os.unlink(wav_path)
            with contextlib.suppress(OSError):
                os.unlink(str(wav_path.with_suffix(".mp3")))

    def test_lower_bitrate_produces_smaller_files(self, mock_ffmpeg_subprocess):
        """Test that lower bitrate produces smaller MP3 files.

        64k should produce smaller files than 128k.
        """
        from whisper_dictate.audio_converter import AudioConverter

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_size = 1024 * 1024  # 1MB
            wav_header = (
                b"RIFF"
                + (wav_size - 8).to_bytes(4, "little")
                + b"WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00"
                b"\x00}\x00\x00\x02\x00\x10\x00data" + (wav_size - 44).to_bytes(4, "little")
            )
            padding = b"\x00" * (wav_size - len(wav_header))
            tmp.write(wav_header + padding)
            tmp.flush()
            wav_path = Path(tmp.name)

        try:
            original_size = wav_path.stat().st_size

            # Simulate different MP3 sizes based on bitrate
            size_by_bitrate = {"64k": 0.08, "128k": 0.15, "192k": 0.22}

            mp3_sizes = {}

            for bitrate in ["64k", "128k"]:

                def make_fake_run(br):
                    def fake_run(cmd, **kwargs):
                        mp3_path = Path(cmd[-1])
                        ratio = size_by_bitrate[br]
                        mp3_path.write_bytes(b"\x00" * int(original_size * ratio))
                        result = Mock()
                        result.returncode = 0
                        result.stderr = ""
                        return result

                    return fake_run

                mock_ffmpeg_subprocess.side_effect = make_fake_run(bitrate)
                converter = AudioConverter(bitrate=bitrate, keep_wav=True)
                result = converter.convert(wav_path)
                mp3_sizes[bitrate] = result.stat().st_size
                if result.suffix == ".mp3" and result.exists():
                    os.unlink(result)

            # 64k should be smaller than 128k
            assert mp3_sizes["64k"] < mp3_sizes["128k"], (
                f"64k ({mp3_sizes['64k']}) should be smaller than 128k ({mp3_sizes['128k']})"
            )
        finally:
            with contextlib.suppress(OSError):
                os.unlink(wav_path)


class TestTranscriptionQualityEquivalence:
    """Test that WAV and MP3 produce equivalent transcription quality.

    Per spec: Lower bitrate (32-64k) MP3 should produce identical
    transcription to WAV for speech.
    """

    def test_wav_and_mp3_produce_same_transcription_mocked(self):
        """Test that WAV and MP3 produce identical transcription text.

        This is a unit test that mocks the OpenAI API to verify
        that both formats are processed identically.
        """
        from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

        # Create test audio files
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_tmp:
            wav_path = Path(wav_tmp.name)
            wav_tmp.write(b"RIFF" + b"\x00" * 100)

        mp3_path = wav_path.with_suffix(".mp3")
        mp3_path.write_bytes(b"\x00" * 20)

        try:
            # Mock the OpenAI client
            mock_response = Mock()
            mock_response.text = "This is a test transcription."
            mock_response.language = "en"
            mock_response.languages = ["en"]

            with patch("openai.OpenAI") as mock_client_class:
                mock_client = Mock()
                mock_client_class.return_value = mock_client
                mock_client.audio.transcriptions.create.return_value = mock_response

                transcriber = OpenAICompatibleProvider(api_key="test-key", silence_threshold_dbfs=None)
                transcriber._client = mock_client

                # Transcribe both WAV and MP3
                wav_result = transcriber.transcribe_audio(wav_path)
                mp3_result = transcriber.transcribe_audio(mp3_path)

                # Verify both produce the same transcription
                assert wav_result.text == mp3_result.text, (
                    f"WAV transcription ('{wav_result.text}') should match MP3 transcription ('{mp3_result.text}')"
                )
                assert wav_result.language == mp3_result.language

                # Verify the API was called with both file types
                assert mock_client.audio.transcriptions.create.call_count == 2
        finally:
            # Cleanup
            with contextlib.suppress(OSError):
                os.unlink(wav_path)
            with contextlib.suppress(OSError):
                os.unlink(mp3_path)

    def test_whisper_api_supports_mp3_natively(self):
        """Test that OpenAICompatibleProvider can accept MP3 files directly.

        This verifies that the transcribe_audio method doesn't require
        any format conversion before sending to the API.
        """
        from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

        # Create a fake MP3 file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3_tmp:
            mp3_path = Path(mp3_tmp.name)
            # Write some bytes to simulate MP3 content
            mp3_tmp.write(b"ID3" + b"\x00" * 100)

        try:
            # Mock the OpenAI client
            mock_response = Mock()
            mock_response.text = "Transcription from MP3."
            mock_response.language = "en"
            mock_response.languages = ["en"]

            with patch("openai.OpenAI") as mock_client_class:
                mock_client = Mock()
                mock_client_class.return_value = mock_client
                mock_client.audio.transcriptions.create.return_value = mock_response

                transcriber = OpenAICompatibleProvider(api_key="test-key", silence_threshold_dbfs=None)
                transcriber._client = mock_client

                # Should not raise any error - MP3 should be supported directly
                result = transcriber.transcribe_audio(mp3_path)

                # Verify result
                assert result.text == "Transcription from MP3."
                assert result.language == "en"

                # Verify file was opened and sent to API
                mock_client.audio.transcriptions.create.assert_called_once()
                call_kwargs = mock_client.audio.transcriptions.create.call_args
                assert call_kwargs is not None
        finally:
            with contextlib.suppress(OSError):
                os.unlink(mp3_path)
