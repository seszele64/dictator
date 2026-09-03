"""Audio format conversion from WAV to MP3 using pydub.

WHY THIS EXISTS: WAV files are large (~10MB per minute at 44.1kHz stereo) and
the Whisper API supports MP3 natively. Converting to MP3 achieves 80-90% size
reduction with no impact on transcription quality for speech.

RESPONSIBILITY: Convert WAV audio files to MP3 format using pydub with FFmpeg backend.
BOUNDARIES:
- DOES: Convert WAV files to MP3, handle graceful fallback when FFmpeg unavailable
- DOES NOT: Handle transcription, recording, or storage management

DEPENDENCIES:
- pydub: Audio format conversion library
- FFmpeg: Audio encoding backend (system dependency)

GRACEFUL DEGRADATION:
- If FFmpeg is unavailable, logs a warning and returns the original WAV path
- The system continues to function with larger file sizes
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioConverter:
    """WHY THIS EXISTS: Encapsulates WAV to MP3 conversion logic with configurable
    bitrate and graceful fallback behavior.

    RESPONSIBILITY: Convert WAV audio files to MP3 format.
    BOUNDARIES:
    - DOES: Convert single WAV file to MP3, respect bitrate settings
    - DOES NOT: Handle batch conversions, audio quality analysis, or format detection

    RELATIONSHIPS:
    - DEPENDS ON: pydub library and FFmpeg backend
    - USED BY: DictationService for pre-upload conversion
    """

    def __init__(self, bitrate: str = "128k", keep_wav: bool = False) -> None:
        """Initialize AudioConverter with conversion settings.

        Args:
            bitrate: MP3 encoding bitrate (e.g., '64k', '128k', '192k').
                    Default is '128k' which provides good balance of size/quality.
            keep_wav: If True, preserve original WAV file after MP3 conversion.
                    Default is False (WAV is deleted after successful conversion).
        """
        self.bitrate = bitrate
        self.keep_wav = keep_wav
        logger.debug(f"AudioConverter initialized: bitrate={bitrate}, keep_wav={keep_wav}")

    def convert(self, wav_path: Path | str, delete_source: bool | None = None) -> Path:
        """Convert a WAV file to MP3 format.

        WHY THIS EXISTS: Provides a simple interface for converting audio files
        before API upload, with graceful fallback when FFmpeg is unavailable.

        RESPONSIBILITY: Convert WAV file to MP3 and optionally delete source.
        BOUNDARIES:
        - DOES: Create MP3 file, optionally delete source WAV
        - DOES NOT: Validate audio content, handle non-WAV input

        Args:
            wav_path: Path to the input WAV file (can be Path or str)
            delete_source: If True, delete the original WAV after successful
                          MP3 creation. If False, preserve the WAV. If None (default),
                          use the keep_wav instance setting.

        Returns:
            Path: Path to the converted MP3 file, or original WAV path if
                  conversion failed (graceful fallback)

        Raises:
            No exceptions - all errors are handled gracefully with logging

        Examples:
            >>> converter = AudioConverter(bitrate="128k")
            >>> mp3_path = converter.convert(Path("/tmp/recording.wav"))
            >>> print(f"Converted to: {mp3_path}")
        """
        # Normalize input to Path
        wav_path = Path(wav_path)
        logger.info(f"Starting WAV to MP3 conversion: {wav_path}")

        # Determine output MP3 path
        mp3_path = wav_path.with_suffix(".mp3")
        logger.debug(f"Output MP3 path: {mp3_path}")

        try:
            # Lazy import pydub to allow graceful absence
            from pydub import AudioSegment

            logger.debug(f"Loading WAV file: {wav_path}")
            audio = AudioSegment.from_wav(str(wav_path))

            logger.debug(f"Encoding MP3 with bitrate={self.bitrate}: {mp3_path}")
            audio.export(
                str(mp3_path),
                format="mp3",
                bitrate=self.bitrate,
            )

            # Calculate file size reduction
            original_size = wav_path.stat().st_size
            converted_size = mp3_path.stat().st_size
            reduction_percent = (original_size - converted_size) / original_size * 100 if original_size > 0 else 0

            logger.info(
                f"Conversion successful: {wav_path.name} -> {mp3_path.name} "
                f"(saved {reduction_percent:.1f}%: {original_size} -> {converted_size} bytes)"
            )

            # Handle source file deletion
            # delete_source=None means use keep_wav setting
            # delete_source=True means definitely delete
            # delete_source=False means definitely keep
            should_delete = not self.keep_wav if delete_source is None else delete_source

            if should_delete and wav_path.exists():
                wav_path.unlink()
                logger.debug(f"Deleted source WAV file: {wav_path}")

            return mp3_path

        except FileNotFoundError as e:
            # FFmpeg not installed
            logger.warning(
                f"FFmpeg not found - conversion failed. "
                f"Install FFmpeg to enable MP3 conversion: sudo pacman -S ffmpeg (Arch) "
                f"or sudo apt install ffmpeg (Debian/Ubuntu). "
                f"Returning original WAV path: {wav_path}. Error: {e}"
            )
            return wav_path

        except Exception as e:
            # Any other conversion error (corrupt file, permissions, etc.)
            logger.warning(
                f"MP3 conversion failed for {wav_path}: {e}. "
                f"Returning original WAV path. "
                f"The system will continue using the larger WAV file."
            )
            return wav_path
