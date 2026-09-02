"""Smoke tests for the root ``toggle_dictate.py`` deprecation shim (P5).

The root file is a pure forwarder to ``whisper_dictate.toggle.main()`` so
existing i3 keybindings / dunst invocations keep working after the P5 fold.
These tests pin exactly that: the shim imports cleanly with no side effects,
and running it as a script announces the deprecation on stderr and forwards
to the package entry point.
"""

import runpy
from pathlib import Path
from unittest.mock import Mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHIM_PATH = REPO_ROOT / "toggle_dictate.py"


def test_shim_exists_at_repo_root():
    """The shim stays in place until the S4 cut-over deletes it."""
    assert SHIM_PATH.is_file()


def test_shim_import_has_no_side_effects(monkeypatch):
    """Executing the shim body with a non-main run name only imports the
    package module; main() must NOT run."""
    forwarded = Mock()
    monkeypatch.setattr("whisper_dictate.toggle.main", forwarded)

    runpy.run_path(str(SHIM_PATH), run_name="p5_shim_import_check")

    forwarded.assert_not_called()


def test_shim_forwards_to_package_main(monkeypatch, capsys):
    """Running the shim as a script prints the deprecation notice on stderr
    and forwards to whisper_dictate.toggle.main()."""
    forwarded = Mock()
    monkeypatch.setattr("whisper_dictate.toggle.main", forwarded)

    runpy.run_path(str(SHIM_PATH), run_name="__main__")

    forwarded.assert_called_once_with()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "deprecated" in captured.err
    assert "whisper-dictate-toggle" in captured.err
