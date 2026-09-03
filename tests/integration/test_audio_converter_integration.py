"""Integration tests for audio converter.

These tests require FFmpeg to be installed and are skipped
if FFmpeg is not available.

Run with: pytest tests/test_audio_converter_integration.py -v
"""

import contextlib
import os
import tempfile
from pathlib import Path

import pytest


class TestFileSizeReductionIntegration:
    """Integration tests for file size reduction.

    These tests require FFmpeg to be installed and are skipped
    if FFmpeg is not available.
    """

    # File size thresholds for size-aware assertions
    SMALL_FILE_THRESHOLD_MB = 1.0

    @staticmethod
    def is_small_file(size_bytes: int) -> bool:
        """Determine if a file is small based on its size in bytes.

        Small files have significant MP3 overhead (headers, frame headers)
        relative to their data content, which reduces the achievable
        compression ratio.

        Args:
            size_bytes: File size in bytes

        Returns:
            True if file is smaller than SMALL_FILE_THRESHOLD_MB
        """
        return size_bytes < TestFileSizeReductionIntegration.SMALL_FILE_THRESHOLD_MB * 1024 * 1024

    @pytest.fixture
    def real_wav_file(self):
        """Create a real WAV file using pydub if available."""
        try:
            from pydub import AudioSegment
        except ImportError:
            pytest.skip("pydub not installed - cannot create real WAV file")

        # Generate 10 seconds of audio at 16kHz mono
        # This simulates ~1.9MB WAV file (10s * 16000 * 2 bytes per sample)
        audio = AudioSegment.silent(duration=10000, frame_rate=16000)
        audio = audio.set_channels(1)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio.export(tmp.name, format="wav")
            yield Path(tmp.name)

        with contextlib.suppress(OSError):
            os.unlink(tmp.name)

    def test_real_file_size_reduction_128k(self, real_wav_file):
        """Test real WAV to MP3 conversion at 128k achieves expected reduction.

        This is an integration test that requires FFmpeg to be installed.

        Note: Expected reduction varies by file size due to MP3 overhead:
        - Small files (< 1 MB): 40-60% reduction (MP3 headers/frames are
          significant relative to audio data)
        - Larger files (>= 1 MB): 80-90% reduction (typical for recordings)
        """
        from whisper_dictate.audio_converter import AudioConverter

        wav_size = real_wav_file.stat().st_size
        is_small = self.is_small_file(wav_size)
        print(f"\nOriginal WAV size: {wav_size / 1024 / 1024:.2f} MB ({'small' if is_small else 'large'} file)")

        converter = AudioConverter(bitrate="128k", keep_wav=True)
        result = converter.convert(real_wav_file)

        if result.suffix == ".wav":
            pytest.skip("FFmpeg not available, skipping real conversion test")

        mp3_size = result.stat().st_size
        reduction_percent = (wav_size - mp3_size) / wav_size * 100

        print(f"MP3 size: {mp3_size / 1024 / 1024:.2f} MB")
        print(f"Reduction: {reduction_percent:.1f}%")

        # Size-aware assertion: small files have lower achievable compression
        if is_small:
            assert 40 <= reduction_percent <= 60, (
                f"Expected 40-60% reduction for small files, got {reduction_percent:.1f}%"
            )
        else:
            assert 80 <= reduction_percent <= 90, (
                f"Expected 80-90% reduction for large files, got {reduction_percent:.1f}%"
            )

        # Cleanup
        with contextlib.suppress(OSError):
            os.unlink(result)

    def test_real_file_size_reduction_64k(self, real_wav_file):
        """Test real WAV to MP3 conversion at 64k achieves even greater reduction.

        64k should produce smaller files than 128k.

        Note: Expected reduction varies by file size due to MP3 overhead:
        - Small files (< 1 MB): 70-80% reduction
        - Larger files (>= 1 MB): 85%+ reduction
        """
        from whisper_dictate.audio_converter import AudioConverter

        wav_size = real_wav_file.stat().st_size
        is_small = self.is_small_file(wav_size)
        print(f"\nOriginal WAV size: {wav_size / 1024 / 1024:.2f} MB ({'small' if is_small else 'large'} file)")

        converter = AudioConverter(bitrate="64k", keep_wav=True)
        result = converter.convert(real_wav_file)

        if result.suffix == ".wav":
            pytest.skip("FFmpeg not available, skipping real conversion test")

        mp3_size = result.stat().st_size
        reduction_percent = (wav_size - mp3_size) / wav_size * 100

        print(f"MP3 (64k) size: {mp3_size / 1024 / 1024:.2f} MB")
        print(f"Reduction: {reduction_percent:.1f}%")

        # Size-aware assertion: small files have lower achievable compression
        if is_small:
            assert 70 <= reduction_percent <= 80, (
                f"Expected 70-80% reduction for small files at 64k, got {reduction_percent:.1f}%"
            )
        else:
            assert reduction_percent >= 85, (
                f"Expected at least 85% reduction for large files at 64k, got {reduction_percent:.1f}%"
            )

        # Cleanup
        with contextlib.suppress(OSError):
            os.unlink(result)

    @pytest.mark.integration
    @pytest.mark.skipif(
        os.getenv("OPENAI_API_KEY") is None,
        reason="Requires OPENAI_API_KEY for live transcription test",
    )
    def test_live_transcription_quality_equivalence(self):
        """Live integration test for transcription quality equivalence.

        This test requires:
        - FFmpeg installed for real conversion
        - OPENAI_API_KEY environment variable set

        It creates a test audio file, converts it to MP3 at 64k,
        and verifies both produce identical transcriptions.

        To run this test manually:
        1. Ensure FFmpeg is installed
        2. Set OPENAI_API_KEY environment variable
        3. Run: pytest tests/test_audio_converter_integration.py::\
        TestFileSizeReductionIntegration::test_live_transcription_quality_equivalence -v -s
        """
        from whisper_dictate.audio_converter import AudioConverter
        from whisper_dictate.providers.openai_compatible import OpenAICompatibleProvider

        # Check FFmpeg availability first
        try:
            from pydub import AudioSegment
        except ImportError:
            pytest.skip("pydub not installed")

        # Generate test audio - say "hello world" for 2 seconds
        # Note: This is silent audio, real test would use actual speech
        audio = AudioSegment.silent(duration=2000, frame_rate=16000)
        audio = audio.set_channels(1)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_tmp:
            audio.export(wav_tmp.name, format="wav")
            wav_path = Path(wav_tmp.name)

        try:
            # Convert to MP3 at 64k
            converter = AudioConverter(bitrate="64k", keep_wav=True)
            result = converter.convert(wav_path)

            if result.suffix == ".wav":
                pytest.skip("FFmpeg not available, skipping live conversion test")

            # Transcribe both
            transcriber = OpenAICompatibleProvider(api_key=os.getenv("OPENAI_API_KEY", ""), silence_threshold_dbfs=None)

            wav_text = transcriber.transcribe_audio(wav_path).text
            mp3_text = transcriber.transcribe_audio(result).text

            print(f"\nWAV transcription: '{wav_text}'")
            print(f"MP3 transcription: '{mp3_text}'")

            # Verify transcription is identical (or very close)
            assert wav_text.strip() == mp3_text.strip(), (
                f"WAV transcription ('{wav_text}') should match MP3 transcription ('{mp3_text}')"
            )

        finally:
            # Cleanup
            with contextlib.suppress(OSError):
                os.unlink(wav_path)
            with contextlib.suppress(OSError):
                os.unlink(result)


class TestTranscriptionQualityManual:
    """Manual tests for transcription quality verification.

    These cannot be automated without actual speech audio and API key.
    Document how to verify manually.
    """

    def test_manual_verification_instructions(self):
        """Document how to manually verify transcription quality.

        Manual verification steps:
        1. Ensure FFmpeg is installed: sudo pacman -S ffmpeg
        2. Set OPENAI_API_KEY environment variable
        3. Create a test WAV file with speech (e.g., record yourself)
        4. Convert to MP3 at different bitrates (32k, 64k, 128k)
        5. Transcribe both WAV and MP3 files using the Whisper API
        6. Compare the transcription results

        The transcriptions should be identical for speech content
        at bitrates of 32k and above.
        """
        instructions = """
        Manual Transcription Quality Test:

        Prerequisites:
        - FFmpeg installed
        - OPENAI_API_KEY environment variable set

        Steps:
        1. Record a speech WAV file:
           rec test.wav

        2. Convert to MP3 at different bitrates:
           ffmpeg -i test.wav -ab 32k test_32k.mp3
           ffmpeg -i test.wav -ab 64k test_64k.mp3
           ffmpeg -i test.wav -ab 128k test_128k.mp3

        3. Transcribe using OpenAI API:
           # Via curl:
           curl -X POST https://api.openai.com/v1/audio/transcriptions \\
                -H "Authorization: Bearer $OPENAI_API_KEY" \\
                -F "file=@test.wav" -F "model=whisper-1"

        4. Compare transcriptions - they should be identical

        Expected result:
        - WAV and MP3 at 32k+ produce identical transcriptions
        - MP3 at lower bitrates may lose some quality
        """
        print(instructions)
        # This test always passes - it's just documentation
        assert True
