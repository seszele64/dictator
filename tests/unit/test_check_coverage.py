"""Tests for scripts/check_coverage.py — the per-module coverage gate.

Verifies the gate handles both relative and absolute path keys in
coverage.json (the JSON reporter relativizes against the report-time
CWD, which may differ from the project root in CI).
"""

import importlib.util
import json
from pathlib import Path

import pytest

# Load scripts/check_coverage.py as a module (it's outside testpaths)
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_coverage.py"
_spec = importlib.util.spec_from_file_location("check_coverage", _SCRIPT_PATH)
check_coverage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_coverage)


def _make_coverage_json(files: dict[str, dict]) -> dict:
    """Build a minimal coverage.json structure with the given file entries."""
    return {
        "files": files,
        "totals": {"percent_covered": 81.02},
    }


def _make_file_entry(pct: float) -> dict:
    return {"summary": {"percent_covered": pct}}


def _passing_files(prefix: str = "") -> dict[str, dict]:
    """One passing entry per module in COVERAGE_THRESHOLDS.

    Keeps the fixtures in sync with the threshold table: adding a module to
    COVERAGE_THRESHOLDS without adding it here makes the pass-case fixtures
    report MISSING modules (the gate counts missing data as failure).
    """
    return {
        f"{prefix}whisper_dictate/database.py": _make_file_entry(94.53),
        f"{prefix}whisper_dictate/config.py": _make_file_entry(100.0),
        f"{prefix}whisper_dictate/db_logging.py": _make_file_entry(100.0),
        f"{prefix}whisper_dictate/migration.py": _make_file_entry(83.27),
        f"{prefix}whisper_dictate/audio_storage.py": _make_file_entry(88.82),
        f"{prefix}whisper_dictate/providers/openai_compatible.py": _make_file_entry(96.72),
        f"{prefix}whisper_dictate/notifications.py": _make_file_entry(44.0),
        f"{prefix}whisper_dictate/dunst_monitor.py": _make_file_entry(66.67),
    }


@pytest.fixture
def tmp_coverage_file(tmp_path):
    """Write a coverage.json to tmp_path and return its Path."""

    def _write(data: dict) -> Path:
        p = tmp_path / "coverage.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    return _write


class TestCheckCoverageRelativePaths:
    """Gate passes with relative path keys (the common case)."""

    def test_all_modules_pass_with_relative_keys(self, tmp_coverage_file):
        path = tmp_coverage_file(_make_coverage_json(_passing_files()))
        assert check_coverage.check_coverage(path) == 0


class TestCheckCoverageAbsolutePaths:
    """Gate passes with absolute path keys (the CI/wrong-CWD scenario)."""

    def test_all_modules_pass_with_absolute_keys(self, tmp_coverage_file):
        prefix = "/root/programming/whisper-dictate/"
        path = tmp_coverage_file(_make_coverage_json(_passing_files(prefix)))
        assert check_coverage.check_coverage(path) == 0


class TestCheckCoverageFailures:
    """Gate fails correctly when thresholds aren't met or data is missing."""

    def test_below_threshold_fails(self, tmp_coverage_file, capsys):
        files = _passing_files()
        files["whisper_dictate/database.py"] = _make_file_entry(50.0)  # below 70%
        path = tmp_coverage_file(_make_coverage_json(files))
        assert check_coverage.check_coverage(path) == 1
        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "database.py" in captured.out

    def test_missing_coverage_file_fails(self, tmp_path, capsys):
        path = tmp_path / "nonexistent.json"
        assert check_coverage.check_coverage(path) == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "not found" in captured.out.lower()
