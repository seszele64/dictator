"""Pre-transcription audio energy analysis to detect silence and prevent Whisper hallucinations.

WHY THIS EXISTS: Whisper hallucinates phrases like "Thank you for watching" on silent audio
(YouTube training data artifact). Detecting silence BEFORE the API call avoids the hallucination
and saves API costs.

RESPONSIBILITY: Analyze audio energy levels to determine if audio contains speech.
BOUNDARIES:
- DOES: Check audio dBFS levels against configurable threshold
- DOES NOT: Perform speech recognition or audio conversion

DEPENDENCIES:
- pydub: Audio analysis library (already used by audio_converter.py)
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def is_audio_silent(audio_file: Path, threshold_dbfs: float = -50.0) -> bool:
    """Check if audio file is silent based on RMS energy level.

    WHY THIS EXISTS: Prevents Whisper API hallucinations on empty/silent audio files.
    When audio is below the threshold, we skip the API call entirely and return an empty
    transcription result.

    RESPONSIBILITY: Analyze audio energy and return silence verdict.
    BOUNDARIES:
    - DOES: Load audio with pydub, measure dBFS, compare to threshold
    - DOES NOT: Transcribe audio, modify files, or handle API calls

    Args:
        audio_file: Path to audio file (WAV, MP3, or any pydub-supported format)
        threshold_dbfs: RMS energy threshold in dBFS. Audio below this is considered silent.
                       Default: -50.0 dBFS. Typical values:
                       - -50.0: Conservative (default) - catches empty recordings
                       - -40.0: Moderate - catches quiet environments
                       - -30.0: Aggressive - only catches near-silence

    Returns:
        True if audio is silent (below threshold), False if it contains speech.
        On error, returns False (fail-open: let the API decide).
    """
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(str(audio_file))
        dbfs = audio.dBFS

        is_silent: bool = dbfs < threshold_dbfs

        logger.debug(
            f"Audio analysis: {audio_file.name} -> {dbfs:.1f} dBFS (threshold={threshold_dbfs:.1f}, silent={is_silent})"
        )

        return is_silent

    except Exception as e:
        # Fail-open: if we can't analyze, let the API try
        logger.warning(f"Failed to analyze audio {audio_file}: {e}. Proceeding with transcription (fail-open).")
        return False
