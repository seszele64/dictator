#!/usr/bin/env python3
"""Deprecated launcher shim for the dictation toggle.

The toggle implementation moved into the package (``whisper_dictate.toggle``)
so it ships an installable console script (``whisper-dictate-toggle``) and a
``whisper-dictate toggle`` command. This root file remains only so existing
i3 keybindings and dunst invocations that reference ``toggle_dictate.py``
keep working unchanged; it is a pure forwarder and will be removed in an
upcoming release. Point keybindings at ``whisper-dictate-toggle`` instead.
"""

import sys

import whisper_dictate.toggle

if __name__ == "__main__":
    # Deprecation notice goes to stderr for one release before the shim is
    # deleted (roadmap §8 mitigation: i3 discards stderr, so keybindings are
    # unaffected by the notice itself).
    print(
        "toggle_dictate.py is deprecated; use the `whisper-dictate-toggle` "
        "console script instead.",
        file=sys.stderr,
    )
    whisper_dictate.toggle.main()
