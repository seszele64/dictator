"""Unit tests for the kept dunst_monitor helpers (S1 purge survivors).

After the S1 purge deleted the DunstMonitor class, the module keeps three
standalone functions used by whisper_dictate.toggle: is_dunst_running(),
start_dunst() and ensure_dunst_running(). These tests pin their actual
branch contract with subprocess fully mocked — no pgrep/ps/dunst binaries
are needed.

Pinned contract of is_dunst_running() (read from the inlined code):
- pgrep runs and finds a process (returncode 0 + non-empty stdout) → True.
- pgrep runs but finds nothing (non-zero returncode) → False. NOTE: a
  non-zero pgrep does NOT trigger the ps fallback — the fallback exists
  only for FileNotFoundError (pgrep binary missing).
- pgrep runs, returncode 0, but stdout is empty → False.
- pgrep raises FileNotFoundError → ps aux fallback: 'dunst' in output
  → True, otherwise → False (ps raising also returns False).
- any other exception → False (warning logged).
"""

import subprocess
from unittest.mock import patch

from whisper_dictate.dunst_monitor import (
    ensure_dunst_running,
    is_dunst_running,
    start_dunst,
)

_PGREP_ARGS = ["pgrep", "-f", "dunst"]
_PS_ARGS = ["ps", "aux"]


def _completed(returncode: int, stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestIsDunstRunning:
    """Branch contract of is_dunst_running()."""

    def test_pgrep_finds_process_returns_true(self):
        """pgrep succeeds with a non-empty process list → True."""
        with patch(
            "whisper_dictate.dunst_monitor.subprocess.run",
            return_value=_completed(0, " 4242 dunst\n"),
        ) as mock_run:
            assert is_dunst_running() is True

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == _PGREP_ARGS

    def test_pgrep_zero_but_empty_stdout_returns_false(self):
        """pgrep succeeds but prints nothing → no process → False."""
        with patch(
            "whisper_dictate.dunst_monitor.subprocess.run",
            return_value=_completed(0, ""),
        ):
            assert is_dunst_running() is False

    def test_pgrep_nonzero_returns_false_without_ps_fallback(self):
        """pgrep runs but finds nothing (returncode 1) → False.

        Pins the actual contract: the ps fallback is reached ONLY via
        FileNotFoundError (missing pgrep binary), not via a non-zero pgrep
        exit code — subprocess.run is called exactly once.
        """
        with patch(
            "whisper_dictate.dunst_monitor.subprocess.run",
            return_value=_completed(1, ""),
        ) as mock_run:
            assert is_dunst_running() is False

        assert mock_run.call_count == 1  # no ps fallback

    def test_pgrep_missing_ps_fallback_finds_process(self):
        """pgrep binary missing (FileNotFoundError) → ps fallback finds
        dunst in its output → True."""
        with patch(
            "whisper_dictate.dunst_monitor.subprocess.run",
            side_effect=[
                FileNotFoundError("pgrep not installed"),
                _completed(0, "root  4242  0.0  0.1  dunst\n"),
            ],
        ) as mock_run:
            assert is_dunst_running() is True

        assert [call[0][0] for call in mock_run.call_args_list] == [
            _PGREP_ARGS,
            _PS_ARGS,
        ]

    def test_pgrep_missing_ps_fallback_no_process(self):
        """pgrep missing and the ps fallback finds no dunst → False."""
        with patch(
            "whisper_dictate.dunst_monitor.subprocess.run",
            side_effect=[
                FileNotFoundError("pgrep not installed"),
                _completed(0, "root    1  0.0  0.1  systemd\n"),
            ],
        ):
            assert is_dunst_running() is False


class TestStartDunst:
    """Smoke test for the spawn-verify logic."""

    def test_start_dunst_success_path(self):
        """start_dunst spawns dunst detached, waits, then verifies via
        is_dunst_running — success path returns True and never raises."""
        with (
            patch("whisper_dictate.dunst_monitor.subprocess.Popen") as mock_popen,
            patch("whisper_dictate.dunst_monitor.time.sleep") as mock_sleep,
            patch("whisper_dictate.dunst_monitor.is_dunst_running", return_value=True) as mock_running,
        ):
            assert start_dunst() is True

        mock_popen.assert_called_once_with(
            ["dunst"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        mock_sleep.assert_called_once()
        mock_running.assert_called_once()


class TestEnsureDunstRunning:
    """Orchestration: verify-first, start-only-when-missing."""

    def test_ensure_skips_start_when_already_running(self):
        with (
            patch("whisper_dictate.dunst_monitor.is_dunst_running", return_value=True),
            patch("whisper_dictate.dunst_monitor.start_dunst") as mock_start,
        ):
            assert ensure_dunst_running() is True
            mock_start.assert_not_called()

    def test_ensure_starts_when_missing(self):
        with (
            patch("whisper_dictate.dunst_monitor.is_dunst_running", return_value=False),
            patch("whisper_dictate.dunst_monitor.start_dunst", return_value=True) as mock_start,
        ):
            assert ensure_dunst_running() is True
            mock_start.assert_called_once()
