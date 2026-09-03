"""Formalized, behavior-faithful fakes for the two I/O seams of DictationService.

These replace ad-hoc ``Mock`` seams with deterministic, dataclass-style fakes
(no ``Mock``, no autospawning attributes). They are consumed by the CLI
snapshot suite (tests/integration/test_cli_snapshots.py) and are available to
future tests via the ``fake_provider`` / ``fake_recorder`` conftest fixtures.

Design rules:
- Signature-faithful: each fake implements exactly the interface production
  code expects (``TranscriptionProvider`` / the ``AudioRecorder`` surface used
  by ``DictationService``), so interface drift fails loudly instead of being
  silently absorbed by permissive mocks.
- Deterministic: scripted outputs are returned in order, no randomness, no
  clocks, no I/O beyond the WAV file FakeRecorder is asked to produce.
- Observable: every call is recorded so tests can assert on the seam traffic.
"""

from dataclasses import dataclass, field
from pathlib import Path

from whisper_dictate.transcription import TranscriptionProvider, TranscriptionResult

# 44-byte minimal valid WAV header (same pattern as conftest.temp_audio_file):
# RIFF/WAVE, PCM mono 16-bit @ 16 kHz, one data chunk of two zero samples.
MINIMAL_WAV_BYTES = (
    b"RIFF\x26\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00"
    b"\x00}\x00\x00\x02\x00\x10\x00data\x02\x00\x00\x00\x00\x00"
)


@dataclass
class FakeProviderCall:
    """One recorded transcribe_audio() invocation."""

    audio_file: Path
    kwargs: dict[str, object] = field(default_factory=dict)


class FakeTranscriptionProvider(TranscriptionProvider):
    """Deterministic stand-in for the real transcription provider.

    Returns scripted ``TranscriptionResult``s in order (the last script entry
    repeats once the script is exhausted) and records every call. When
    ``error`` is set, ``transcribe_audio`` raises that exception instead -
    for error-path tests that must pin the CLI's failure output.

    The signature intentionally mirrors ``TranscriptionProvider`` exactly;
    if the production interface grows parameters, this fake must be updated
    in lockstep, which is precisely the drift the snapshot suite watches for.
    """

    def __init__(
        self,
        results: list[TranscriptionResult] | None = None,
        *,
        error: Exception | None = None,
        provider_name: str = "fake",
    ) -> None:
        self._script = (
            list(results) if results else [TranscriptionResult(text="Hello from the fake provider.", language="en")]
        )
        # Mutable on purpose: tests assign `fake.error = ...` to script an
        # error path (see test_snapshot_dictate_transcription_error).
        self.error: Exception | None = error
        self._provider_name = provider_name
        self.calls: list[FakeProviderCall] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def transcribe_audio(self, audio_file: Path) -> TranscriptionResult:
        """Exact production signature (TranscriptionProvider.transcribe_audio).

        Deliberately NOT more permissive: if the interface grows parameters,
        this fake raises TypeError and the interface change must be made
        consciously in lockstep.
        """
        self.calls.append(FakeProviderCall(audio_file=audio_file))
        if self.error is not None:
            raise self.error
        index = min(len(self.calls), len(self._script)) - 1
        return self._script[index]


@dataclass
class FakeRecorderCall:
    """One recorded record_to_file() invocation."""

    duration: float | None


class FakeRecorder:
    """Deterministic stand-in for ``AudioRecorder`` at the DictationService seam.

    ``record_to_file`` writes a minimal valid WAV file under ``tmp_dir`` (the
    same role the real recorder's temp file plays) and returns its path, so
    the real ``AudioStorage`` staging/save path downstream sees a real file.
    Every call is recorded; when ``error`` is set the call raises instead,
    letting tests pin recording-failure output.
    """

    def __init__(
        self,
        tmp_dir: Path | str,
        *,
        error: Exception | None = None,
        wav_bytes: bytes = MINIMAL_WAV_BYTES,
    ) -> None:
        self._tmp_dir = Path(tmp_dir)
        self._error = error
        self._wav_bytes = wav_bytes
        self.calls: list[FakeRecorderCall] = []
        self._files_written: list[Path] = []

    def record_to_file(self, duration: float | None = None) -> Path:
        self.calls.append(FakeRecorderCall(duration=duration))
        if self._error is not None:
            raise self._error
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        path = self._tmp_dir / f"fake-recording-{len(self.calls)}.wav"
        path.write_bytes(self._wav_bytes)
        self._files_written.append(path)
        return path

    def get_audio_devices(self) -> tuple[str, ...]:
        """Mirror AudioRecorder.get_audio_devices() for info-style callers."""
        return ("fake-device",)

    @property
    def files_written(self) -> list[Path]:
        """WAV files this fake produced (still existing or already consumed)."""
        return list(self._files_written)
