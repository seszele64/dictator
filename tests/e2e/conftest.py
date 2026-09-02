"""E2E suite notes — deliberately NO skip-if-missing-binaries guard.

Roadmap P4 suggested skipping e2e tests when dunstify/xclip are absent from
PATH. That guard was evaluated and intentionally NOT installed: every e2e
test here mocks the system binaries at their seams (arecord via
toggle_dictate.subprocess.Popen, dunstify/clipboard via subprocess.run mocks —
see the test_dictation_pipeline.py docstring), so the suite passes on
machines without dunstify or xclip. A path-based guard would therefore skip
7 real tests on every CI container for no reason, hiding their coverage.

If a future e2e test ever invokes a real system binary directly, guard that
test (or its fixture) individually instead of reinstating a directory-wide
skip.
"""
