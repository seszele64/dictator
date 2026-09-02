"""Tests for whisper_dictate.toggle (the dictation toggle).

The toggle was folded into the package in P5; since S4 its transcribe step
delegates to ``DictationService.transcribe_existing()`` (covered from the
service side in tests/integration/test_dictation.py). These tests patch the
package module directly (the real code paths): the state-machine tests pin
the arecord/PID lifecycle, the wrapper tests pin the delegation contract.
"""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from whisper_dictate import toggle


class TestTranscribeAudio:
    """Test the transcribe_audio wrapper (S4: delegates to DictationService).

    The heavy lifting (claim-first save, duration probe, transcript rows,
    clipboard) lives in DictationService.transcribe_existing and is tested
    in tests/integration/test_dictation.py. These pins cover the wrapper
    contract: construction, delegation arguments, the recording_id state
    fallback, notifications, and AUDIO_FILE cleanup on every path.
    """

    def _run_transcribe(
        self,
        recording_id=42,
        text="Hello world",
        silence=False,
        service_error=None,
    ):
        """Drive toggle.transcribe_audio with DictationService mocked.

        Returns (result, service_cls, service, mock_db, audio_file, mocks).
        """
        mock_config = MagicMock()
        mock_config.openai.model = "whisper-1"

        mock_db = MagicMock()
        mock_db.get_state = Mock(return_value=42)

        result = SimpleNamespace(text=text, language="en", silence_detected=silence)

        audio_file = MagicMock(spec=Path)
        audio_file.exists.return_value = True

        with (
            patch.object(toggle, "get_db_and_storage", return_value=(mock_db, Mock())),
            patch.object(toggle, "DictationService") as service_cls,
            patch.object(toggle, "AUDIO_FILE", audio_file),
            patch.object(toggle, "notify_recording_stopped") as notify_stopped,
            patch.object(toggle, "notify_error") as notify_error,
        ):
            service = service_cls.return_value.__enter__.return_value
            if service_error is not None:
                service.transcribe_existing.side_effect = service_error
            else:
                service.transcribe_existing.return_value = result

            returned = toggle.transcribe_audio(mock_config, recording_id=recording_id)

        return SimpleNamespace(
            returned=returned,
            service_cls=service_cls,
            service=service,
            mock_db=mock_db,
            audio_file=audio_file,
            notify_stopped=notify_stopped,
            notify_error=notify_error,
        )

    def test_delegates_to_dictation_service(self):
        """Text path: construct with config, delegate with the pinned args."""
        ctx = self._run_transcribe(recording_id=42, text="Hello world")

        ctx.service_cls.assert_called_once()
        assert ctx.service_cls.call_args.args[0] is not None  # the config
        ctx.service.transcribe_existing.assert_called_once_with(
            42, ctx.audio_file, copy_to_clipboard=True
        )
        assert ctx.returned == "Hello world"
        ctx.notify_stopped.assert_called_once_with("Hello world")
        ctx.notify_error.assert_not_called()
        ctx.audio_file.unlink.assert_called_once()
        ctx.mock_db.close.assert_called_once()

    def test_recording_id_falls_back_to_state(self):
        """recording_id=None is resolved from db state before delegation."""
        ctx = self._run_transcribe(recording_id=None, text="Hello world")

        ctx.mock_db.get_state.assert_called_once_with(toggle.STATE_KEY_RECORDING_ID)
        ctx.service.transcribe_existing.assert_called_once_with(
            42, ctx.audio_file, copy_to_clipboard=True
        )
        assert ctx.returned == "Hello world"
        ctx.audio_file.unlink.assert_called_once()

    def test_service_failure_returns_none_and_notifies(self):
        """A service exception becomes (None + error notification), still unlinks."""
        ctx = self._run_transcribe(service_error=RuntimeError("boom"))

        assert ctx.returned is None
        ctx.notify_error.assert_called_once_with("Transcription failed: boom")
        ctx.notify_stopped.assert_not_called()
        ctx.audio_file.unlink.assert_called_once()
        ctx.mock_db.close.assert_called_once()

    def test_missing_audio_file_returns_none_without_delegation(self):
        """The AUDIO_FILE guard: no service construction, no unlink, None."""
        mock_config = MagicMock()
        audio_file = MagicMock(spec=Path)
        audio_file.exists.return_value = False

        with (
            patch.object(toggle, "get_db_and_storage") as mock_get_db_storage,
            patch.object(toggle, "DictationService") as service_cls,
            patch.object(toggle, "AUDIO_FILE", audio_file),
        ):
            returned = toggle.transcribe_audio(mock_config, recording_id=42)

        assert returned is None
        service_cls.assert_not_called()
        mock_get_db_storage.assert_not_called()
        audio_file.unlink.assert_not_called()


class TestTranscribeAudioSilenceDetection:
    """Silence vs. speech handling in the toggle's transcribe_audio wrapper."""

    def test_transcribe_silent_returns_empty_and_notifies(self):
        """Silence: delegate, notify the silence message, return ""."""
        ctx = TestTranscribeAudio._run_transcribe(
            None, recording_id=42, text="", silence=True
        )

        ctx.service.transcribe_existing.assert_called_once_with(
            42, ctx.audio_file, copy_to_clipboard=True
        )
        assert ctx.returned == ""
        ctx.notify_stopped.assert_called_once_with("Silence detected - no speech")
        ctx.audio_file.unlink.assert_called_once()

    def test_transcribe_non_silent_proceeds_normally(self):
        """Non-silent: the text path notifies with the transcription text."""
        ctx = TestTranscribeAudio._run_transcribe(
            None, recording_id=42, text="Hello world"
        )

        assert ctx.returned == "Hello world"
        ctx.notify_stopped.assert_called_once_with("Hello world")
        ctx.notify_error.assert_not_called()
        ctx.audio_file.unlink.assert_called_once()


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
