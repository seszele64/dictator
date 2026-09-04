"""Pre-transcription audio energy analysis to detect silence and prevent Whisper hallucinations.

WHY THIS EXISTS: Whisper hallucinates phrases like "Thank you for watching" on silent audio
(YouTube training data artifact). Detecting silence BEFORE the API call avoids the hallucination
and saves API costs.

RESPONSIBILITY: Analyze audio energy levels to determine if audio contains speech.
BOUNDARIES:
- DOES: Check audio dBFS levels against configurable threshold
- DOES NOT: Perform speech recognition or audio conversion

DEPENDENCIES:
- soundfile: audio decoding (bundled libsndfile; WAV I/O and MP3 decode)
- numpy: RMS math

dBFS SEMANTICS (ADR 0006): identical to the pre-P10 implementation this
module replaces — that stack computed 20*log10(rms/32768) over the
interleaved 16-bit PCM stream (audioop.rms semantics, all channels
flattened); here samples are read normalized to ±1.0 (float32), where a
16-bit sample s maps to s/32768, so 20*log10(rms(normalized)) equals that
value exactly (goldens in tests/integration/test_audio_golden.py pin the
equivalence, including asymmetric stereo and the -inf result for digital
silence).
"""

import logging
import math
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


def is_audio_silent(audio_file: Path, threshold_dbfs: float = -50.0) -> bool:
    """Check if audio file is silent based on RMS energy level.

    WHY THIS EXISTS: Prevents Whisper API hallucinations on empty/silent audio files.
    When audio is below the threshold, we skip the API call entirely and return an empty
    transcription result.

    RESPONSIBILITY: Analyze audio energy and return silence verdict.
    BOUNDARIES:
    - DOES: Load audio with soundfile, measure dBFS, compare to threshold
    - DOES NOT: Transcribe audio, modify files, or handle API calls

    Args:
        audio_file: Path to audio file (WAV, MP3, or any soundfile-supported format)
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
        # str() on the path: callers/tests pin that soundfile receives a str.
        samples, _sample_rate = sf.read(str(audio_file), dtype="float32")

        # Flatten all channels into one rms (matches the replaced
        # implementation, whose audioop.rms ran over the interleaved byte
        # stream of every channel).
        data = np.asarray(samples, dtype=np.float64)
        rms = 0.0 if data.size == 0 else float(math.sqrt(float(np.mean(data * data))))

        # Digital silence (rms == 0) is -inf dBFS — same as the pre-P10 dBFS.
        dbfs = -math.inf if rms == 0.0 else 20.0 * math.log10(rms)

        is_silent: bool = dbfs < threshold_dbfs

        logger.debug(
            f"Audio analysis: {audio_file.name} -> {dbfs:.1f} dBFS (threshold={threshold_dbfs:.1f}, silent={is_silent})"
        )

        return is_silent

    except Exception as e:
        # Fail-open: if we can't analyze, let the API try
        logger.warning(f"Failed to analyze audio {audio_file}: {e}. Proceeding with transcription (fail-open).")
        return False
