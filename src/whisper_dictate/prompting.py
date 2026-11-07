"""Interactive prompt acquisition for post-processing.

WHY THIS EXISTS: The ``process`` command needs a prompt from one of several
sources — a scriptable ``--prompt`` flag, an interactive rofi/dmenu popup, or a
``POST_PROCESS_PROMPT`` preset. The launcher/fallback matrix and the
cancellation-vs-failure semantics are the most failure-prone part of the
feature, so they live in a dedicated, subprocess-mockable module instead of
being inlined into the CLI.

RESPONSIBILITY: Resolve a prompt string from the explicit flag, an interactive
launcher (rofi preferred, dmenu fallback), or the environment preset.
BOUNDARIES:
- DOES: Run launchers with argv lists and ``shell=False``; distinguish silent
  cancellation from launcher failure
- DOES NOT: Talk to any model, touch the database, or send notifications

RELATIONSHIPS:
- USED BY: the ``process`` CLI command
"""

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

# A wedged launcher must not hang the command; this is a safety bound, not a
# user-facing prompt budget.
_LAUNCHER_TIMEOUT_SECONDS = 10


class PromptUnavailableError(Exception):
    """Raised when no prompt source is available or a launcher fails.

    Distinct from a silent cancellation (``None``): this is a real failure the
    CLI reports with an error notification and a non-zero exit.
    """


def _run_launcher(argv: list[str], stdin_text: str | None) -> str | None:
    """Run a launcher and return its stdout, or None on cancellation.

    Args:
        argv: The launcher command as an argv list (never a shell string).
        stdin_text: Text to write to the launcher's stdin, or None for no input.

    Returns:
        str | None: The stripped stdout when non-empty; None when the launcher
        exited non-zero (Escape) or produced empty/whitespace-only output.

    Raises:
        PromptUnavailableError: If the launcher does not exit within the timeout.
    """
    try:
        result = subprocess.run(
            argv,
            input=stdin_text,
            capture_output=True,
            text=True,
            shell=False,
            timeout=_LAUNCHER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PromptUnavailableError(
            f"Prompt launcher '{argv[0]}' did not exit within {_LAUNCHER_TIMEOUT_SECONDS} seconds."
        ) from exc
    except OSError as exc:
        raise PromptUnavailableError(f"Failed to run prompt launcher '{argv[0]}': {exc}") from exc

    if result.returncode != 0:
        # Escape / dismissal: a silent cancel, not an error.
        return None

    output = result.stdout.strip()
    if not output:
        return None
    return output


def acquire_prompt(explicit: str | None, preset: str) -> str | None:
    """Resolve a prompt from the flag, an interactive launcher, or the preset.

    Precedence:
    1. A non-empty (stripped) ``explicit`` value is returned immediately; no
       subprocess is started and the preset is ignored.
    2. Otherwise, if ``rofi`` is on PATH, run ``rofi -dmenu -p "Prompt:"``,
       adding ``-filter <preset>`` when the preset is non-empty.
    3. Else, if ``dmenu`` is on PATH, run ``dmenu -p "Prompt:"``; the preset (if
       any) is written to stdin as the single entry, otherwise stdin is empty.
    4. Else, if the preset is non-empty, return it without a popup.
    5. Else raise ``PromptUnavailableError``.

    Args:
        explicit: The ``--prompt`` value, or None when not supplied. Empty or
            whitespace-only values are treated as not supplied.
        preset: The ``POST_PROCESS_PROMPT`` value (may be empty).

    Returns:
        str | None: The prompt, or None for a silent cancellation (Escape or
        blank input).

    Raises:
        PromptUnavailableError: If no prompt source is available, or a launcher
        times out. A timeout is never reported as a cancellation.
    """
    if explicit is not None and explicit.strip():
        return explicit.strip()

    if shutil.which("rofi"):
        argv = ["rofi", "-dmenu", "-p", "Prompt:"]
        if preset:
            argv += ["-filter", preset]
        return _run_launcher(argv, None)

    if shutil.which("dmenu"):
        argv = ["dmenu", "-p", "Prompt:"]
        stdin_text = preset + "\n" if preset else ""
        return _run_launcher(argv, stdin_text)

    if preset:
        return preset

    raise PromptUnavailableError(
        "No prompt source available: pass --prompt, set POST_PROCESS_PROMPT, or install rofi/dmenu."
    )
