"""Unit tests for whisper_dictate.prompting (Group 2).

Covers the prompt-source precedence (``--prompt`` -> rofi -> dmenu -> preset ->
error), the exact launcher argv/stdin contract, and the cancellation-vs-failure
semantics (non-zero exit / blank output cancel silently; a timeout or an
``OSError`` is an error, never a cancellation).

``subprocess.run`` and ``shutil.which`` are mocked throughout — no launcher is
ever started.
"""

import subprocess
from unittest.mock import Mock, patch

import pytest

from whisper_dictate.prompting import (
    PromptUnavailableError,
    acquire_prompt,
)

_TIMEOUT = 10


def _which(*available: str):
    """Build a ``shutil.which`` replacement reporting only the named binaries."""

    available_set = set(available)

    def _impl(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in available_set else None

    return _impl


def _completed(stdout: str = "", returncode: int = 0) -> Mock:
    """Build a minimal ``subprocess.CompletedProcess``-shaped mock."""
    result = Mock()
    result.stdout = stdout
    result.returncode = returncode
    return result


class TestExplicitPrecedence:
    """A non-empty ``--prompt`` wins and starts no subprocess."""

    def test_explicit_value_is_returned_and_no_subprocess_starts(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi", "dmenu")),
            patch("whisper_dictate.prompting.subprocess.run") as m_run,
        ):
            assert acquire_prompt("Summarize this", "preset") == "Summarize this"

        m_run.assert_not_called()

    def test_explicit_value_is_stripped(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run") as m_run,
        ):
            assert acquire_prompt("  Summarize this  ", "") == "Summarize this"

        m_run.assert_not_called()

    @pytest.mark.parametrize("explicit", ["", "   ", "\t\n"])
    def test_blank_explicit_is_treated_as_absent(self, explicit):
        """Empty/whitespace-only flags fall through to the launcher."""
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("typed")) as m_run,
        ):
            assert acquire_prompt(explicit, "") == "typed"

        m_run.assert_called_once()

    def test_explicit_ignores_the_preset(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run") as m_run,
        ):
            assert acquire_prompt("flag wins", "preset loses") == "flag wins"

        m_run.assert_not_called()


class TestRofiBranch:
    """rofi is preferred and receives the documented argv."""

    def test_rofi_argv_without_preset(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("typed")) as m_run,
        ):
            assert acquire_prompt(None, "") == "typed"

        m_run.assert_called_once_with(
            ["rofi", "-dmenu", "-p", "Prompt:"],
            input=None,
            capture_output=True,
            text=True,
            shell=False,
            timeout=_TIMEOUT,
        )

    def test_rofi_argv_with_preset_adds_filter(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("Rewrite formally")) as m_run,
        ):
            assert acquire_prompt(None, "Rewrite formally") == "Rewrite formally"

        m_run.assert_called_once_with(
            ["rofi", "-dmenu", "-p", "Prompt:", "-filter", "Rewrite formally"],
            input=None,
            capture_output=True,
            text=True,
            shell=False,
            timeout=_TIMEOUT,
        )

    def test_rofi_is_preferred_when_both_are_available(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi", "dmenu")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("x")) as m_run,
        ):
            acquire_prompt(None, "")

        assert m_run.call_args.args[0][0] == "rofi"


class TestDmenuBranch:
    """dmenu is the fallback and carries the preset on stdin."""

    def test_dmenu_argv_and_empty_stdin_without_preset(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("dmenu")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("typed")) as m_run,
        ):
            assert acquire_prompt(None, "") == "typed"

        m_run.assert_called_once_with(
            ["dmenu", "-p", "Prompt:"],
            input="",
            capture_output=True,
            text=True,
            shell=False,
            timeout=_TIMEOUT,
        )

    def test_dmenu_stdin_carries_preset_with_trailing_newline(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("dmenu")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("Rewrite formally")) as m_run,
        ):
            assert acquire_prompt(None, "Rewrite formally") == "Rewrite formally"

        assert m_run.call_args.kwargs["input"] == "Rewrite formally\n"
        assert m_run.call_args.args[0] == ["dmenu", "-p", "Prompt:"]


class TestPresetFallback:
    """The preset is used without a popup when no launcher exists."""

    def test_preset_used_when_no_launcher_is_installed(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which()),
            patch("whisper_dictate.prompting.subprocess.run") as m_run,
        ):
            assert acquire_prompt(None, "Rewrite formally") == "Rewrite formally"

        m_run.assert_not_called()


class TestNoSourceAvailable:
    """No flag, no launcher, no preset is a hard error."""

    def test_no_source_raises_and_starts_no_subprocess(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which()),
            patch("whisper_dictate.prompting.subprocess.run") as m_run,
            pytest.raises(PromptUnavailableError),
        ):
            acquire_prompt(None, "")

        m_run.assert_not_called()


class TestLauncherOutcomes:
    """Cancellation, trimming, and the timeout/OSError failure paths."""

    def test_nonzero_returncode_is_a_silent_cancellation(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("ignored", returncode=1)),
        ):
            assert acquire_prompt(None, "") is None

    def test_empty_stdout_is_a_silent_cancellation(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("")),
        ):
            assert acquire_prompt(None, "") is None

    def test_whitespace_only_stdout_is_a_silent_cancellation(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("  \t\n ")),
        ):
            assert acquire_prompt(None, "") is None

    def test_successful_output_is_stripped(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", return_value=_completed("  hello  ")),
        ):
            assert acquire_prompt(None, "") == "hello"

    def test_timeout_is_an_error_not_a_cancellation(self):
        exc = subprocess.TimeoutExpired(cmd=["rofi"], timeout=_TIMEOUT)
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", side_effect=exc),
            pytest.raises(PromptUnavailableError, match="did not exit"),
        ):
            acquire_prompt(None, "")

    def test_oserror_is_an_error(self):
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", side_effect=OSError("boom")),
            pytest.raises(PromptUnavailableError, match="Failed to run prompt launcher"),
        ):
            acquire_prompt(None, "")

    def test_timeout_message_names_the_launcher(self):
        exc = subprocess.TimeoutExpired(cmd=["rofi"], timeout=_TIMEOUT)
        with (
            patch("whisper_dictate.prompting.shutil.which", _which("rofi")),
            patch("whisper_dictate.prompting.subprocess.run", side_effect=exc),
            pytest.raises(PromptUnavailableError) as excinfo,
        ):
            acquire_prompt(None, "")

        assert "rofi" in str(excinfo.value)
