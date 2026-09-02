"""E2E tests for the full dictation pipeline in toggle_dictate.py.

Runs the real pipeline (start -> stop -> transcribe) against a real SQLite
database and real filesystem audio storage, mocking only audio capture
(arecord), the transcription API, the clipboard, and notifications.
"""

import contextlib
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest

import toggle_dictate
from whisper_dictate.config import DatabaseConfig
from whisper_dictate.database import Database
from whisper_dictate.transcription import TranscriptionResult

# Minimal valid WAV header (44 bytes) - same pattern as conftest.temp_audio_file
WAV_HEADER = (
    b"RIFF\x26\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00"
    b"\x00}\x00\x00\x02\x00\x10\x00data\x02\x00\x00\x00\x00\x00"
)

# Mock PID reported by the mocked arecord subprocess
MOCK_PROCESS_PID = 12345


@dataclass
class E2EEnv:
    """References to the mocked dependencies and temp dirs for E2E tests."""

    transcriber: Mock
    clipboard: Mock
    popen: Mock
    tmp_path: Path


@pytest.fixture
def e2e_env(tmp_path, monkeypatch, db_singleton_reset, mock_config):
    """Set up the full E2E environment.

    Uses a real SQLite database and real audio storage in temp directories.
    Only audio capture (arecord), the transcription API, the clipboard, and
    notifications are mocked. Singleton reset is handled by db_singleton_reset.
    """
    # Redirect module-level file paths to the temp directory
    monkeypatch.setattr(toggle_dictate, "STATE_FILE", tmp_path / "state")
    monkeypatch.setattr(toggle_dictate, "PID_FILE", tmp_path / "pid")
    monkeypatch.setattr(toggle_dictate, "AUDIO_FILE", tmp_path / "audio.wav")

    # Point the pipeline's config at temp dirs so real SQLite + storage never
    # touch HOME. The pipeline reads DatabaseConfig through AppConfig.database
    # (config passed explicitly) and via bootstrap() when no config is given
    # (stop_background_recording), so patch both seams.
    test_db_config = DatabaseConfig(
        path=tmp_path / "test.db",
        recordings_path=tmp_path / "recordings",
    )
    mock_config.database = test_db_config
    monkeypatch.setattr(toggle_dictate, "bootstrap", lambda *a, **k: mock_config)

    # Mock the arecord subprocess (returns a process with a fake PID)
    popen_mock = Mock()
    popen_mock.return_value = Mock(pid=MOCK_PROCESS_PID)
    monkeypatch.setattr(toggle_dictate.subprocess, "Popen", popen_mock)

    # Mock os.kill to prevent real signals to the fake PID (12345)
    monkeypatch.setattr(toggle_dictate.os, "kill", Mock())

    # Mock the transcription API factory
    transcriber = Mock()
    transcriber.transcribe_audio.return_value = TranscriptionResult(
        text="Hello world", language="en"
    )
    monkeypatch.setattr(
        toggle_dictate, "create_transcriber", Mock(return_value=transcriber)
    )

    # Mock the clipboard
    clipboard = Mock()
    clipboard.copy_to_clipboard.return_value = True
    monkeypatch.setattr(toggle_dictate, "ClipboardManager", Mock(return_value=clipboard))

    # Mock soundfile.info duration probe (real float for SQLite storage)
    audio_info = Mock()
    audio_info.duration = 2.5
    monkeypatch.setattr(toggle_dictate.sf, "info", Mock(return_value=audio_info))

    # Mock notifications (they invoke subprocess.run for dunstify)
    for name in (
        "notify_recording_start",
        "notify_recording_stopped",
        "notify_stopping_transcription",
        "notify_recording_stop",
        "notify_error",
    ):
        monkeypatch.setattr(toggle_dictate, name, Mock())

    # Pre-create the audio file (arecord is mocked, so it would not exist)
    toggle_dictate.AUDIO_FILE.write_bytes(WAV_HEADER)

    yield E2EEnv(
        transcriber=transcriber,
        clipboard=clipboard,
        popen=popen_mock,
        tmp_path=tmp_path,
    )
    # Teardown: db_singleton_reset closes/resets the database and audio storage singletons


@contextlib.contextmanager
def _verify_db(tmp_path: Path):
    """Open a fresh Database instance for verification queries.

    Independent of the module singleton used by the pipeline, so it can be
    created after pipeline functions have run and closed their connections.
    """
    db = Database(
        DatabaseConfig(
            path=tmp_path / "test.db",
            recordings_path=tmp_path / "recordings",
        )
    )
    db.initialize()
    try:
        yield db
    finally:
        with contextlib.suppress(Exception):
            db.close()


class TestDictationPipelineE2E:
    """End-to-end tests exercising the real dictation pipeline."""

    def _start_stop(self, e2e_env: E2EEnv, mock_config) -> int:
        """Run start + stop through the real pipeline and return the recording_id."""
        process = toggle_dictate.start_background_recording(mock_config)
        assert process is not None, "expected recording process to start"
        success, recording_id = toggle_dictate.stop_background_recording()
        assert success is True
        assert recording_id is not None
        return recording_id

    def test_full_dictation_cycle(self, e2e_env, mock_config):
        """The full cycle persists the recording + transcript and copies to clipboard."""
        e2e_env.transcriber.transcribe_audio.return_value = TranscriptionResult(
            text="Hello world", language="en"
        )

        process = toggle_dictate.start_background_recording(mock_config)
        assert process is not None
        assert process.pid == MOCK_PROCESS_PID
        assert toggle_dictate.PID_FILE.exists()
        assert toggle_dictate.STATE_FILE.exists()

        success, recording_id = toggle_dictate.stop_background_recording()
        assert success is True
        assert recording_id is not None
        assert not toggle_dictate.PID_FILE.exists()
        assert not toggle_dictate.STATE_FILE.exists()

        text = toggle_dictate.transcribe_audio(mock_config, recording_id)
        assert text == "Hello world"

        with _verify_db(e2e_env.tmp_path) as db:
            recording = db.fetchone(
                "SELECT file_path, duration, format FROM recordings WHERE id = ?",
                (recording_id,),
            )
            assert recording is not None
            file_path, duration, fmt = recording
            assert file_path is not None
            assert duration == 2.5
            assert fmt == "wav"

            transcript = db.fetchone(
                "SELECT text, language, model_used FROM transcripts WHERE recording_id = ?",
                (recording_id,),
            )
            assert transcript == ("Hello world", "en", "whisper-1")

        e2e_env.clipboard.copy_to_clipboard.assert_called_once_with("Hello world")

        saved_audio = list((e2e_env.tmp_path / "recordings").rglob("*.wav"))
        assert len(saved_audio) == 1
        assert not toggle_dictate.AUDIO_FILE.exists()

    def test_silence_detected_cycle(self, e2e_env, mock_config):
        """Silence skips the clipboard but still persists the empty transcript + audio."""
        e2e_env.transcriber.transcribe_audio.return_value = TranscriptionResult(
            text="", silence_detected=True
        )

        recording_id = self._start_stop(e2e_env, mock_config)
        text = toggle_dictate.transcribe_audio(mock_config, recording_id)
        assert text == ""

        e2e_env.clipboard.copy_to_clipboard.assert_not_called()

        with _verify_db(e2e_env.tmp_path) as db:
            transcript = db.fetchone(
                "SELECT text, language FROM transcripts WHERE recording_id = ?",
                (recording_id,),
            )
            assert transcript == ("", None)

        assert list((e2e_env.tmp_path / "recordings").rglob("*.wav"))

    def test_start_sets_recording_state(self, e2e_env, mock_config):
        """Starting sets DB state, creates a recording row, and writes PID/STATE files."""
        process = toggle_dictate.start_background_recording(mock_config)
        assert process is not None

        with _verify_db(e2e_env.tmp_path) as db:
            assert db.get_state("is_recording") is True
            recording_id = db.get_state("current_recording_id")
            assert isinstance(recording_id, int)

            row = db.fetchone(
                "SELECT file_path, format, sample_rate, channels "
                "FROM recordings WHERE id = ?",
                (recording_id,),
            )
            assert row is not None
            # fix-storage-safety claim-first: start stores an empty file_path
            # sentinel (the raw arecord temp path lies outside the recordings
            # root); the real contained path is claimed in after the save.
            assert row[0] == ""
            assert row[1] == "wav"
            assert row[2] == 44100
            assert row[3] == 2

        assert toggle_dictate.PID_FILE.exists()
        assert toggle_dictate.PID_FILE.read_text().strip() == str(MOCK_PROCESS_PID)
        assert toggle_dictate.STATE_FILE.exists()

        toggle_dictate.stop_background_recording()

    def test_stop_clears_recording_state(self, e2e_env, mock_config):
        """Stopping clears DB state and removes the PID/STATE files."""
        process = toggle_dictate.start_background_recording(mock_config)
        assert process is not None

        success, recording_id = toggle_dictate.stop_background_recording()
        assert success is True
        assert recording_id is not None

        with _verify_db(e2e_env.tmp_path) as db:
            assert db.get_state("is_recording") is False
            assert db.get_state("current_recording_id") is None

        assert not toggle_dictate.PID_FILE.exists()
        assert not toggle_dictate.STATE_FILE.exists()

    def test_transcribe_updates_recording_duration(self, e2e_env, mock_config):
        """Transcription persists the audio duration onto the recording row."""
        e2e_env.transcriber.transcribe_audio.return_value = TranscriptionResult(
            text="Hello", language="en"
        )

        recording_id = self._start_stop(e2e_env, mock_config)
        toggle_dictate.transcribe_audio(mock_config, recording_id)

        with _verify_db(e2e_env.tmp_path) as db:
            row = db.fetchone(
                "SELECT duration FROM recordings WHERE id = ?", (recording_id,)
            )
            assert row == (2.5,)

    def test_transcribe_saves_audio_to_storage(self, e2e_env, mock_config):
        """Audio is moved into the recordings dir and DB stores a relative path."""
        e2e_env.transcriber.transcribe_audio.return_value = TranscriptionResult(
            text="Hello", language="en"
        )

        recording_id = self._start_stop(e2e_env, mock_config)
        toggle_dictate.transcribe_audio(mock_config, recording_id)

        saved_audio = list((e2e_env.tmp_path / "recordings").rglob("*.wav"))
        assert len(saved_audio) == 1

        with _verify_db(e2e_env.tmp_path) as db:
            row = db.fetchone(
                "SELECT file_path FROM recordings WHERE id = ?", (recording_id,)
            )
            assert row is not None
            assert not Path(row[0]).is_absolute()

    def test_transcribe_creates_transcript_with_correct_fields(self, e2e_env, mock_config):
        """Transcript rows carry the text, language, and model used."""
        e2e_env.transcriber.transcribe_audio.return_value = TranscriptionResult(
            text="Test transcript", language="en"
        )

        recording_id = self._start_stop(e2e_env, mock_config)
        toggle_dictate.transcribe_audio(mock_config, recording_id)

        with _verify_db(e2e_env.tmp_path) as db:
            row = db.fetchone(
                "SELECT text, language, model_used "
                "FROM transcripts WHERE recording_id = ?",
                (recording_id,),
            )
            assert row == ("Test transcript", "en", "whisper-1")
