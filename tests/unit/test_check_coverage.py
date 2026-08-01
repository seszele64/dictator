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
        data = _make_coverage_json({
            "whisper_dictate/database.py": _make_file_entry(94.53),
            "whisper_dictate/config.py": _make_file_entry(100.0),
            "whisper_dictate/db_logging.py": _make_file_entry(100.0),
            "whisper_dictate/migration.py": _make_file_entry(83.27),
            "whisper_dictate/audio_storage.py": _make_file_entry(88.82),
            "whisper_dictate/providers/openai_compatible.py": _make_file_entry(96.72),
        })
        path = tmp_coverage_file(data)
        assert check_coverage.check_coverage(path) == 0


class TestCheckCoverageAbsolutePaths:
    """Gate passes with absolute path keys (the CI/wrong-CWD scenario)."""

    def test_all_modules_pass_with_absolute_keys(self, tmp_coverage_file):
        data = _make_coverage_json({
            "/root/programming/whisper-dictate/whisper_dictate/database.py": _make_file_entry(94.53),
            "/root/programming/whisper-dictate/whisper_dictate/config.py": _make_file_entry(100.0),
            "/root/programming/whisper-dictate/whisper_dictate/db_logging.py": _make_file_entry(100.0),
            "/root/programming/whisper-dictate/whisper_dictate/migration.py": _make_file_entry(83.27),
            "/root/programming/whisper-dictate/whisper_dictate/audio_storage.py": _make_file_entry(88.82),
            "/root/programming/whisper-dictate/whisper_dictate/providers/openai_compatible.py": _make_file_entry(96.72),
        })
        path = tmp_coverage_file(data)
        assert check_coverage.check_coverage(path) == 0


class TestCheckCoverageFailures:
    """Gate fails correctly when thresholds aren't met or data is missing."""

    def test_below_threshold_fails(self, tmp_coverage_file, capsys):
        data = _make_coverage_json({
            "whisper_dictate/database.py": _make_file_entry(50.0),  # below 70%
            "whisper_dictate/config.py": _make_file_entry(100.0),
            "whisper_dictate/db_logging.py": _make_file_entry(100.0),
            "whisper_dictate/migration.py": _make_file_entry(83.27),
            "whisper_dictate/audio_storage.py": _make_file_entry(88.82),
            "whisper_dictate/providers/openai_compatible.py": _make_file_entry(96.72),
        })
        path = tmp_coverage_file(data)
        assert check_coverage.check_coverage(path) == 1
        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "database.py" in captured.out

    def test_missing_coverage_file_fails(self, tmp_path, capsys):
        path = tmp_path / "nonexistent.json"
        assert check_coverage.check_coverage(path) == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "not found" in captured.out.lower()
