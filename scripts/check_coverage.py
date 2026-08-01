"""Enforce per-module coverage thresholds from coverage.json.

Reads the coverage.json produced by `pytest --cov-report=json` and checks
each target module against its minimum coverage threshold. Exits non-zero
if any module falls short of its target.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Per-module coverage thresholds
# (from spec: openspec/changes/2026-08-01-test-safety-net/specs/test-infrastructure/spec.md)
COVERAGE_THRESHOLDS: dict[str, float] = {
    "whisper_dictate/database.py": 70.0,
    "whisper_dictate/config.py": 80.0,
    "whisper_dictate/db_logging.py": 60.0,
    "whisper_dictate/migration.py": 50.0,
    "whisper_dictate/audio_storage.py": 80.0,
    "whisper_dictate/providers/openai_compatible.py": 80.0,
}


def _print_table(rows: list[tuple[str, float, float, str]]) -> None:
    """Print the per-module coverage table to stdout."""
    module_width = max(len(module) for module in COVERAGE_THRESHOLDS)
    header = f"{'Module':<{module_width}} | {'Cover%':>7} | {'Target':>7} | Status"
    separator = "-" * len(header)
    print(header)
    print(separator)
    for module, cover, target, status in rows:
        print(f"{module:<{module_width}} | {cover:>6.2f}% | {target:>6.2f}% | {status}")
    print(separator)


def check_coverage(coverage_file: Path) -> int:
    """Enforce per-module thresholds, returning 0 on success and 1 on failure."""
    try:
        with coverage_file.open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: coverage file not found: {coverage_file}", file=sys.stderr)
        print("Run tests with --cov-report=json to generate it.", file=sys.stderr)
        return 1

    files = data.get("files", {})
    overall = float(data.get("totals", {}).get("percent_covered", 0.0))

    rows: list[tuple[str, float, float, str]] = []
    missing: list[str] = []
    failed: list[tuple[str, float, float]] = []

    for module, target in COVERAGE_THRESHOLDS.items():
        file_data = files.get(module)
        if file_data is None:
            missing.append(module)
            rows.append((module, 0.0, target, "MISSING"))
            continue
        cover = float(file_data.get("summary", {}).get("percent_covered", 0.0))
        ok = cover >= target
        rows.append((module, cover, target, "PASS" if ok else "FAIL"))
        if not ok:
            failed.append((module, cover, target))

    print()
    _print_table(rows)
    print(f"Overall coverage: {overall:.2f}%")

    if missing:
        print()
        print("MISSING MODULES (no coverage data):")
        for module in missing:
            print(f"  - {module}")

    if failed:
        print()
        print("FAILED MODULES:")
        for module, cover, target in failed:
            shortfall = target - cover
            print(f"  - {module}: {cover:.2f}% < {target:.2f}% target (short by {shortfall:.2f}pp)")

    if missing or failed:
        print()
        print("Coverage gate FAILED: per-module thresholds not met.")
        return 1

    print()
    print("Coverage gate PASSED: all per-module thresholds met.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-file", default="coverage.json", help="Path to coverage.json")
    args = parser.parse_args()
    return check_coverage(Path(args.coverage_file))


if __name__ == "__main__":
    sys.exit(main())
