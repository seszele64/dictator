"""Live-mode provider contract test (spec 008, P11).

The only suite test that performs real network I/O: config → factory →
`OpenAICompatibleProvider` → real WAV upload → `TranscriptionResult`.

Skipped by default (and always in CI). Opt in with a real API key:

    WHISPER_DICTATE_LIVE_CONTRACT=1 OPENAI_API_KEY=<key> \
        uv run pytest tests/contract/test_live_provider.py -q

Provider/key selection mirrors `config.py`: `WHISPER_PROVIDER` (default
"openai") picks the provider whose `PROVIDER_DEFAULTS` env var supplies the
API key. Without a valid key the real API rejects the request — the failure
itself proves the seam reaches the network.
"""

import importlib
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from whisper_dictate.config import PROVIDER_DEFAULTS, WhisperConfig, WhisperProvider
from whisper_dictate.transcription import TranscriptionResult, create_transcriber


def _write_real_wav(path: Path) -> None:
    """Synthesize a 0.2 s valid WAV with the REAL soundfile module.

    tests/conftest.py installs a Mock `soundfile` into sys.modules for the
    whole session (audio-hang guard), so a plain `import soundfile` would get
    the mock. Pop it, import the real module, write the WAV, then restore the
    mock so the session-wide audio-module invariant stays untouched.
    """
    saved = sys.modules.pop("soundfile", None)
    try:
        sf = importlib.import_module("soundfile")
        samples = (0.1 * np.sin(2.0 * np.pi * 440.0 * np.arange(3200) / 16000.0)).astype(np.float32)
        sf.write(str(path), samples, 16000, subtype="PCM_16")
    finally:
        for name in [m for m in sys.modules if m == "soundfile" or m.startswith("soundfile.")]:
            del sys.modules[name]
        if saved is not None:
            sys.modules["soundfile"] = saved


@pytest.mark.contract
@pytest.mark.contract_live
@pytest.mark.skipif(
    not os.getenv("WHISPER_DICTATE_LIVE_CONTRACT"),
    reason="live provider contract test; opt in via WHISPER_DICTATE_LIVE_CONTRACT",
)
def test_live_openai_compatible_transcribe(tmp_path: Path):
    """Real minimal transcription through the provider seam (network I/O)."""
    provider_name = os.getenv("WHISPER_PROVIDER", "openai")
    try:
        provider_enum = WhisperProvider(provider_name)
    except ValueError:
        provider_enum = WhisperProvider.CUSTOM
    env_var = PROVIDER_DEFAULTS[provider_enum]["env_var"]
    config = WhisperConfig(
        provider=provider_name,
        api_key=os.getenv(env_var, "") if env_var else "",
        # Silence detection needs soundfile, mocked out at session scope;
        # the seam under test here is the real API round-trip.
        silence_threshold_dbfs=None,
    )
    transcriber = create_transcriber(config)
    wav = tmp_path / "live.wav"
    _write_real_wav(wav)
    result = transcriber.transcribe_audio(wav)
    assert isinstance(result, TranscriptionResult)
