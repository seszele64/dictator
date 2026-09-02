"""Tests for whisper_dictate.toggle (the dictation toggle).

The toggle implementation was folded from the root ``toggle_dictate.py``
script into the package in P5; these tests patch the package module directly
(the real code paths). The root ``toggle_dictate.py`` file is only a
deprecation shim (see tests/unit/test_toggle_shim.py).
"""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from whisper_dictate import toggle


class TestTranscribeAudio:
    """Test the transcribe_audio function."""

    def test_duration_calculated_and_saved(self):
        """Test that recording duration is calculated and saved to database.

        This is a regression test for the bug where recording duration was not
        calculated from the actual audio file using soundfile.info() after
        recording stops.
        """
        # Create mock config
        mock_config = MagicMock()
        mock_config.openai.model = "whisper-1"

        # Create mock database with properly configured sync methods
        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.get_state = Mock(return_value=42)
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()
        mock_db.set_state = Mock()
        mock_db.delete_state = Mock()

        # Mock audio storage
        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (
            Path("/saved/test.wav"),
            "test.wav",
        )
        mock_audio_storage.recordings_path = Path("/recordings")

        # Create mock audio info that soundfile.info() will return
        mock_audio_info = Mock()
        mock_audio_info.duration = 5.0

        # Mock result from WhisperTranscriber
        mock_transcription_result = MagicMock()
        mock_transcription_result.text = "This is a test transcription."
        mock_transcription_result.language = "en"
        mock_transcription_result.silence_detected = False

        # Create mock Path object for AUDIO_FILE
        mock_audio_file = MagicMock(spec=Path)
        mock_audio_file.exists.return_value = True
        mock_audio_file.unlink.return_value = None

        with (
            patch.object(toggle, "get_db_and_storage") as mock_get_db_storage,
            patch(
                "whisper_dictate.toggle.sf.info", return_value=mock_audio_info
            ) as mock_sf_info,
            patch("whisper_dictate.toggle.create_transcriber") as mock_create_transcriber,
            patch("whisper_dictate.toggle.AUDIO_FILE", mock_audio_file),
            patch("whisper_dictate.toggle.ClipboardManager") as mock_clipboard_class,
        ):
            # Setup mocks
            mock_get_db_storage.return_value = (mock_db, mock_audio_storage)
            mock_transcriber_instance = MagicMock()
            mock_create_transcriber.return_value = mock_transcriber_instance
            mock_transcriber_instance.transcribe_audio.return_value = (
                mock_transcription_result
            )
            mock_clipboard_instance = MagicMock()
            mock_clipboard_class.return_value = mock_clipboard_instance

            # Call transcribe_audio
            result = toggle.transcribe_audio(mock_config, recording_id=42)

            # Verify result
            assert result == "This is a test transcription."

            # Verify db.execute was called with UPDATE to set duration
            mock_db.execute.assert_called()

            # Get the SQL query and parameters from the execute call
            call_args = mock_db.execute.call_args

            # Verify the call was made with duration 5.0
            assert call_args is not None
            args = call_args[0] if call_args[0] else ()
            kwargs = call_args[1] if len(call_args) > 1 else {}

            # Check that duration 5.0 is in the call arguments
            found_duration = (
                5.0 in args
                or kwargs.get("duration") == 5.0
                or any(
                    hasattr(arg, "__iter__") and 5.0 in arg
                    for arg in args
                    if not isinstance(arg, str)
                )
            )
            assert found_duration, (
                f"Expected duration 5.0 in execute call, got {call_args}"
            )

            # Verify soundfile.info was called
            mock_sf_info.assert_called_once()


class TestTranscribeAudioSilenceDetection:
    """Test silence detection behavior in the toggle's transcribe_audio."""

    def test_transcribe_silent_skips_clipboard(self):
        """Test that silent audio skips clipboard copy."""
        mock_config = MagicMock()
        mock_config.openai.model = "whisper-1"

        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.get_state = Mock(return_value=42)
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()
        mock_db.set_state = Mock()
        mock_db.delete_state = Mock()

        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (Path("/saved/test.wav"), "test.wav")
        mock_audio_storage.recordings_path = Path("/recordings")

        mock_audio_info = Mock()
        mock_audio_info.duration = 5.0

        # Create silent result
        mock_silent_result = MagicMock()
        mock_silent_result.text = ""
        mock_silent_result.language = None
        mock_silent_result.silence_detected = True

        mock_audio_file = MagicMock(spec=Path)
        mock_audio_file.exists.return_value = True
        mock_audio_file.unlink.return_value = None

        with (
            patch.object(toggle, "get_db_and_storage") as mock_get_db_storage,
            patch("whisper_dictate.toggle.sf.info", return_value=mock_audio_info),
            patch("whisper_dictate.toggle.create_transcriber") as mock_create_transcriber,
            patch("whisper_dictate.toggle.AUDIO_FILE", mock_audio_file),
            patch("whisper_dictate.toggle.ClipboardManager") as mock_clipboard_class,
        ):
            mock_get_db_storage.return_value = (mock_db, mock_audio_storage)
            mock_transcriber_instance = MagicMock()
            mock_create_transcriber.return_value = mock_transcriber_instance
            mock_transcriber_instance.transcribe_audio.return_value = mock_silent_result
            mock_clipboard_instance = MagicMock()
            mock_clipboard_class.return_value = mock_clipboard_instance

            toggle.transcribe_audio(mock_config, recording_id=42)

            # Should NOT copy to clipboard
            mock_clipboard_instance.copy_to_clipboard.assert_not_called()

            # Should store empty transcript
            mock_db.create_transcript.assert_called()
            call_kwargs = mock_db.create_transcript.call_args.kwargs
            assert call_kwargs["text"] == ""

    def test_transcribe_non_silent_proceeds_normally(self):
        """Test that non-silent audio proceeds with normal workflow."""
        mock_config = MagicMock()
        mock_config.openai.model = "whisper-1"

        mock_db = MagicMock()
        mock_db.path = Path("/tmp/test.db")
        mock_db.initialize = Mock()
        mock_db.get_state = Mock(return_value=42)
        mock_db.create_recording = Mock(return_value=42)
        mock_db.create_transcript = Mock(return_value=1)
        mock_db.execute = Mock()
        mock_db.create_log = Mock(return_value=1)
        mock_db.connection = Mock()
        mock_db.close = Mock()
        mock_db.set_state = Mock()
        mock_db.delete_state = Mock()

        mock_audio_storage = MagicMock()
        mock_audio_storage.save_audio.return_value = (Path("/saved/test.wav"), "test.wav")
        mock_audio_storage.recordings_path = Path("/recordings")

        mock_audio_info = Mock()
        mock_audio_info.duration = 5.0

        # Create normal result
        mock_normal_result = MagicMock()
        mock_normal_result.text = "Hello world"
        mock_normal_result.language = "en"
        mock_normal_result.silence_detected = False

        mock_audio_file = MagicMock(spec=Path)
        mock_audio_file.exists.return_value = True
        mock_audio_file.unlink.return_value = None

        with (
            patch.object(toggle, "get_db_and_storage") as mock_get_db_storage,
            patch("whisper_dictate.toggle.sf.info", return_value=mock_audio_info),
            patch("whisper_dictate.toggle.create_transcriber") as mock_create_transcriber,
            patch("whisper_dictate.toggle.AUDIO_FILE", mock_audio_file),
            patch("whisper_dictate.toggle.ClipboardManager") as mock_clipboard_class,
        ):
            mock_get_db_storage.return_value = (mock_db, mock_audio_storage)
            mock_transcriber_instance = MagicMock()
            mock_create_transcriber.return_value = mock_transcriber_instance
            mock_transcriber_instance.transcribe_audio.return_value = mock_normal_result
            mock_clipboard_instance = MagicMock()
            mock_clipboard_class.return_value = mock_clipboard_instance

            toggle.transcribe_audio(mock_config, recording_id=42)

            # Should copy to clipboard
            mock_clipboard_instance.copy_to_clipboard.assert_called_once_with("Hello world")


# ---------------------------------------------------------------------------
# P5 toggle state-machine pins: is_recording sources, PID handling,
# start/stop transitions, and main() dispatch.
# ---------------------------------------------------------------------------

_NOTIFY_NAMES = (
    "notify_recording_start",
    "notify_recording_stopped",
    "notify_stopping_transcription",
    "notify_recording_stop",
    "notify_error",
)


class TestToggleStateMachine:
    """State-machine pins for the toggle, against the package module."""

    @pytest.fixture
    def toggle_env(self, tmp_path, monkeypatch):
        """Isolated toggle environment.

        Legacy dotfiles are redirected into tmp_path, the DB/storage seam is
        mocked, subprocess/os seams and notifications are mocked. bootstrap
        is patched so no test ever loads real configuration.
        """
        monkeypatch.setattr(toggle, "STATE_FILE", tmp_path / "state")
        monkeypatch.setattr(toggle, "PID_FILE", tmp_path / "pid")
        monkeypatch.setattr(toggle, "AUDIO_FILE", tmp_path / "audio.wav")

        db = Mock()
        db.get_state = Mock(return_value=None)
        db.create_recording = Mock(return_value=7)
        storage = Mock()
        monkeypatch.setattr(
            toggle, "get_db_and_storage", Mock(return_value=(db, storage))
        )

        popen = Mock()
        popen.return_value = Mock(pid=4242)
        monkeypatch.setattr(toggle.subprocess, "Popen", popen)
        monkeypatch.setattr(toggle.os, "kill", Mock())

        notifies = {name: Mock() for name in _NOTIFY_NAMES}
        for name, mock in notifies.items():
            monkeypatch.setattr(toggle, name, mock)

        monkeypatch.setattr(toggle, "bootstrap", Mock())
        monkeypatch.setattr(toggle, "setup_logging", Mock())

        return SimpleNamespace(
            db=db, popen=popen, notifies=notifies, tmp_path=tmp_path
        )

    # ---- is_recording: DB first, legacy files as fallback ----

    def test_is_recording_db_true_short_circuits(self, toggle_env):
        """DB state wins: no legacy files needed when the DB says recording."""
        toggle_env.db.get_state = Mock(return_value=True)
        assert toggle.is_recording(object()) is True
        toggle_env.db.close.assert_called_once()

    def test_is_recording_db_false_falls_back_to_files(self, toggle_env, tmp_path):
        """Legacy file fallback: DB says no, but PID+STATE files exist."""
        toggle_env.db.get_state = Mock(return_value=False)
        (tmp_path / "state").touch()
        (tmp_path / "pid").write_text("4242\n")
        assert toggle.is_recording(object()) is True

    def test_is_recording_db_false_no_files_is_false(self, toggle_env):
        """Neither DB nor files report recording."""
        toggle_env.db.get_state = Mock(return_value=False)
        assert toggle.is_recording(object()) is False

    def test_is_recording_db_error_falls_back_to_files(self, monkeypatch, tmp_path):
        """A database failure degrades to the file-based fallback."""
        monkeypatch.setattr(toggle, "STATE_FILE", tmp_path / "state")
        monkeypatch.setattr(toggle, "PID_FILE", tmp_path / "pid")
        monkeypatch.setattr(
            toggle, "get_db_and_storage", Mock(side_effect=RuntimeError("db down"))
        )
        assert toggle.is_recording(None) is False
        (tmp_path / "state").touch()
        (tmp_path / "pid").write_text("1\n")
        assert toggle.is_recording(None) is True

    # ---- get_recording_pid ----

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (None, None),  # no PID file
            ("not-a-pid", None),  # unparsable
            ("4242\n", 4242),  # valid with trailing newline
        ],
    )
    def test_get_recording_pid(self, toggle_env, content, expected):
        if content is not None:
            toggle_env.tmp_path.joinpath("pid").write_text(content)
        assert toggle.get_recording_pid() == expected

    # ---- start_background_recording ----

    def test_start_writes_pid_state_and_db_row(self, toggle_env):
        """Start records the arecord PID, the state marker, and the DB row."""
        process = toggle.start_background_recording(object())
        assert process is not None
        assert process.pid == 4242
        assert (toggle_env.tmp_path / "pid").read_text() == "4242"
        assert (toggle_env.tmp_path / "state").exists()

        toggle_env.db.create_recording.assert_called_once_with(
            file_path="",  # claim-first sentinel: real path claimed after save
            duration=None,
            format="wav",
            sample_rate=44100,
            channels=2,
        )
        toggle_env.db.set_state.assert_any_call(toggle.STATE_KEY_RECORDING, True)
        toggle_env.db.set_state.assert_any_call(
            toggle.STATE_KEY_RECORDING_ID, 7
        )
        toggle_env.notifies["notify_recording_start"].assert_called_once()
        toggle_env.db.close.assert_called_once()

    def test_start_failure_returns_none_and_notifies(self, toggle_env, monkeypatch):
        """A missing arecord binary degrades to (None + error notification)."""
        monkeypatch.setattr(
            toggle.subprocess,
            "Popen",
            Mock(side_effect=FileNotFoundError("arecord missing")),
        )
        assert toggle.start_background_recording(object()) is None
        toggle_env.notifies["notify_error"].assert_called_once()
        assert not (toggle_env.tmp_path / "pid").exists()

    def test_start_survives_db_entry_failure(self, toggle_env, monkeypatch):
        """A DB failure must not kill the recording process start (warn only)."""
        toggle_env.db.create_recording = Mock(side_effect=RuntimeError("db down"))
        process = toggle.start_background_recording(object())
        assert process is not None
        assert (toggle_env.tmp_path / "pid").exists()
        toggle_env.notifies["notify_recording_start"].assert_called_once()

    # ---- stop_background_recording ----

    def test_stop_kills_pid_and_clears_files_and_state(
        self, toggle_env, monkeypatch, tmp_path
    ):
        """Stop signals arecord twice (TERM then KILL), removes both legacy
        files, clears DB state, and returns the recording_id for transcription."""
        (tmp_path / "pid").write_text("4242")
        (tmp_path / "state").touch()
        toggle_env.db.get_state = Mock(return_value=7)

        kill = Mock()
        monkeypatch.setattr(toggle.os, "kill", kill)

        success, recording_id = toggle.stop_background_recording(object())

        assert success is True
        assert recording_id == 7
        assert kill.call_count == 2
        kill.assert_any_call(4242, toggle.signal.SIGTERM)
        kill.assert_any_call(4242, toggle.signal.SIGKILL)
        assert not (tmp_path / "pid").exists()
        assert not (tmp_path / "state").exists()
        toggle_env.db.set_state.assert_called_once_with(
            toggle.STATE_KEY_RECORDING, False
        )
        toggle_env.db.delete_state.assert_called_once_with(
            toggle.STATE_KEY_RECORDING_ID
        )
        toggle_env.db.close.assert_called_once()

    def test_stop_without_pid_still_clears_state_file(self, toggle_env, tmp_path):
        """No PID file: nothing signaled, but the state marker is still cleared."""
        (tmp_path / "state").touch()
        success, recording_id = toggle.stop_background_recording(object())
        assert success is True
        assert recording_id is None
        assert not (tmp_path / "state").exists()
        toggle.os.kill.assert_not_called()

    # ---- main() dispatch ----

    def _patch_dispatch(self, monkeypatch, **overrides):
        """Patch main()'s collaborators for dispatch tests."""
        defaults = {
            "ensure_dunst_running": Mock(return_value=True),
            "is_recording": Mock(return_value=False),
            "start_background_recording": Mock(return_value=Mock(pid=1)),
            "stop_background_recording": Mock(return_value=(True, 7)),
            "transcribe_audio": Mock(return_value="text"),
        }
        defaults.update(overrides)
        for name, mock in defaults.items():
            monkeypatch.setattr(toggle, name, mock)
        return SimpleNamespace(**defaults)

    def test_main_starts_recording_when_not_recording(self, toggle_env, monkeypatch):
        """Not recording → start path (no stop/transcribe)."""
        mocks = self._patch_dispatch(monkeypatch)
        toggle.main()
        mocks.start_background_recording.assert_called_once()
        mocks.stop_background_recording.assert_not_called()
        mocks.transcribe_audio.assert_not_called()

    def test_main_proceeds_when_dunst_missing(self, toggle_env, monkeypatch):
        """A missing dunst daemon only warns - recording still starts."""
        mocks = self._patch_dispatch(
            monkeypatch, ensure_dunst_running=Mock(return_value=False)
        )
        toggle.main()
        mocks.start_background_recording.assert_called_once()

    def test_main_stops_and_transcribes_when_recording(self, toggle_env, monkeypatch):
        """Recording → stop, then transcribe with the returned recording_id."""
        mocks = self._patch_dispatch(monkeypatch, is_recording=Mock(return_value=True))
        toggle.main()
        toggle_env.notifies["notify_stopping_transcription"].assert_called_once()
        toggle_env.notifies["notify_recording_stop"].assert_called_once()
        mocks.stop_background_recording.assert_called_once()
        mocks.transcribe_audio.assert_called_once()
        assert mocks.transcribe_audio.call_args.args[1] == 7
        mocks.start_background_recording.assert_not_called()

    def test_main_exits_1_when_start_fails(self, toggle_env, monkeypatch):
        """A failed start exits with code 1 (the i3-visible failure code)."""
        self._patch_dispatch(
            monkeypatch, start_background_recording=Mock(return_value=None)
        )
        with pytest.raises(SystemExit) as excinfo:
            toggle.main()
        assert excinfo.value.code == 1

    def test_main_requires_api_key_before_recording(self, toggle_env, monkeypatch):
        """W2: startup validates the API key again (legacy fail-fast restored).

        bootstrap() must be called with require_api_key=True; a keyless
        startup notifies the error and exits 1 BEFORE any recording process
        is spawned or any state is touched. The `whisper-dictate toggle`
        subcommand inherits this pin because it forwards to toggle.main().
        """
        bootstrap = Mock(side_effect=ValueError("API key not found"))
        monkeypatch.setattr(toggle, "bootstrap", bootstrap)
        mocks = self._patch_dispatch(monkeypatch)

        with pytest.raises(SystemExit) as excinfo:
            toggle.main()

        assert excinfo.value.code == 1
        bootstrap.assert_called_once_with(require_api_key=True)
        toggle_env.notifies["notify_error"].assert_called_once_with("API key not found")
        toggle_env.popen.assert_not_called()
        mocks.start_background_recording.assert_not_called()
        mocks.stop_background_recording.assert_not_called()
        mocks.transcribe_audio.assert_not_called()

    def test_main_error_path_notifies_and_cleans_up(
        self, toggle_env, monkeypatch, tmp_path
    ):
        """An unexpected error notifies, stops recording, and removes audio."""
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"RIFF")
        mocks = self._patch_dispatch(
            monkeypatch, is_recording=Mock(side_effect=RuntimeError("boom"))
        )
        toggle.main()
        toggle_env.notifies["notify_error"].assert_called_once()
        mocks.stop_background_recording.assert_called_once()
        assert not audio_path.exists()


class TestToggleLogging:
    """The toggle's logging setup must keep using the AppPaths log location."""

    def test_setup_logging_writes_to_app_paths_log_file(self, env_isolator):
        """FileHandler points at AppPaths().log_file (XDG state home)."""
        from whisper_dictate.config import AppPaths

        root = logging.getLogger()
        prior_handlers = root.handlers[:]
        prior_level = root.level
        try:
            toggle.setup_logging()
            expected = AppPaths().log_file
            file_handlers = [
                h for h in root.handlers if isinstance(h, logging.FileHandler)
            ]
            assert file_handlers, "expected a file handler after setup_logging"
            assert file_handlers[0].baseFilename == str(expected)
            assert expected.exists(), "log file should have been created"
        finally:
            # setup_logging clears the handler list; undo its global changes so
            # neither pytest's capture handlers nor the root level leak.
            for handler in root.handlers[:]:
                if handler not in prior_handlers:
                    handler.close()
            root.handlers[:] = prior_handlers
            root.setLevel(prior_level)

    def test_setup_logging_closes_preexisting_handlers(self, env_isolator):
        """W3: re-setup CLOSES the handlers it replaces before clearing.

        A cleared-but-open handler keeps its resource alive (the CLI group
        callback's DatabaseLogHandler holds a database open until click
        teardown), so close must precede the clear.
        """
        root = logging.getLogger()
        prior_handlers = root.handlers[:]
        prior_level = root.level
        stale = Mock(spec=logging.Handler)
        root.addHandler(stale)
        try:
            toggle.setup_logging()
            stale.close.assert_called_once()
        finally:
            for handler in root.handlers[:]:
                if handler not in prior_handlers:
                    handler.close()
            root.handlers[:] = prior_handlers
            root.setLevel(prior_level)
