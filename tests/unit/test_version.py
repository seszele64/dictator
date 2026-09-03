"""Version wiring tests: package __version__ must agree with its metadata.

WHY: the version is defined once in src/whisper_dictate/__init__.py and read by
hatchling for the distribution (pyproject.toml uses dynamic = ["version"]).
These tests fail loudly if the single source of truth drifts from the
installed distribution metadata or if the CLI's --version flag stops
reporting it.
"""

import re
import tomllib
from importlib import metadata
from pathlib import Path

from click.testing import CliRunner

from whisper_dictate import __version__
from whisper_dictate.cli import cli

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[.+][0-9A-Za-z.-]+)?$")


def test_version_is_a_valid_release_string():
    assert isinstance(__version__, str)
    assert _SEMVER_RE.match(__version__), f"not a valid version: {__version__!r}"


def test_pyproject_declares_dynamic_version_from_package_init():
    """pyproject must not carry a second, static copy of the version.

    With dynamic versioning the distribution version is resolved from
    whisper_dictate/__init__.py, so tomllib sees no static `version` key —
    its presence would mean two sources of truth that can drift.
    """
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert "version" not in data["project"]
    assert "version" in data["project"]["dynamic"]
    assert data["tool"]["hatch"]["version"]["path"] == "src/whisper_dictate/__init__.py"


def test_dunder_version_matches_installed_distribution_metadata():
    """The package attribute and the installed dist metadata must agree."""
    assert __version__ == metadata.version("whisper-dictate")


def test_cli_version_flag_exits_zero_and_reports_version():
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0, result.output
    assert __version__ in result.output
    assert "whisper-dictate" in result.output
