"""E2E suite notes — deliberately NO skip-if-missing-binaries guard.

Roadmap P4 suggested skipping e2e tests when dunstify/xclip are absent from
PATH. That guard was evaluated and intentionally NOT installed: every e2e
test here mocks the system binaries at their seams (arecord via
whisper_dictate.toggle's subprocess.Popen; the transcription API, clipboard,
and soundfile duration probe at their whisper_dictate.dictation seams since
the S4 delegation; notifications via the toggle's dunstify wrappers — see
the test_dictation_pipeline.py docstring), so the
suite passes on machines without dunstify or xclip. A path-based guard would
therefore skip 7 real tests on every CI container for no reason, hiding their
coverage.

If a future e2e test ever invokes a real system binary directly, guard that
test (or its fixture) individually instead of reinstating a directory-wide
skip.
"""
