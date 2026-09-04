# ADR 6: Replace pydub with soundfile and an FFmpeg subprocess

## Status

Accepted (2026-09-04)

## Context

The audio stack used pydub 0.25.1 for three things: decoding WAV files,
exporting MP3 (via its FFmpeg backend), and measuring dBFS for silence
detection. pydub imports the standard-library `audioop` module, which Python
3.13 removed (PEP 594) — so real pydub usage was dead on 3.13 from the start,
and the P9 CI matrix had to carry an `allow-fail` bridge for the 3.13 leg to
keep the pipeline green. Upstream pydub is unmaintained (last release
2021), so no fix was coming. Meanwhile the actual usage surface was tiny:
one decode path, one export call, and one dBFS formula — none of it
justifying an incompatible, unmaintained dependency.

## Decision

Replace pydub with two smaller, maintained pieces (owner decision D4,
"ffmpeg-only-when-needed"):

- **soundfile + numpy** own audio decode/analysis: `soundfile` (libsndfile
  wheels bundled) reads WAV files, numpy computes the RMS. This covers
  everything `is_audio_silent` ever needed.
- **One FFmpeg subprocess call** performs MP3 encoding, invoked only when a
  conversion is actually requested. The argv contract
  (`ffmpeg -y -i <in> -codec:a libmp3lame -b:a <bitrate> <out>`) is now
  maintained in-repo and pinned by an argv test plus the golden round-trips.
- **Golden behavior tests FIRST**: `tests/integration/test_audio_golden.py`
  pinned sample rate, frame counts, duration, and dBFS boundaries (15
  goldens) and ran green against pydub BEFORE the swap and after it —
  converter outputs are byte-identical across the regimes (34029 B at 128k,
  17037 B at 64k for the 2 s golden source).
- **numpy is declared a direct runtime dependency**, not a transitive one —
  the modules import it directly, and direct-import hygiene says it belongs
  in `[project.dependencies]`.

## Consequences

- **Positive**: Genuine Python 3.13 support — the CI `allow-fail` bridge is
  deleted and 3.13 joins the must-pass matrix
- **Positive**: One fewer runtime dependency; both replacements are actively
  maintained (soundfile wheels bundle libsndfile, ffmpeg is a system binary
  the project already required)
- **Positive**: dBFS is mathematically identical:
  `20·log10(rms/32768)` ≡ `20·log10(sqrt(mean(x²)))` for float-normalized
  samples; only audioop's integer-rounding display at very low amplitudes
  differs (~0.1 dB, inside the golden tolerance and documented there)
- **Negative**: The ffmpeg argv contract is now maintained in-repo instead
  of delegated to pydub (mitigated: pinned by an argv unit test and the
  converter round-trip goldens, which fail loudly on drift)

## Related Files

- `src/whisper_dictate/audio_converter.py` - FFmpeg subprocess MP3 encoder
- `src/whisper_dictate/audio_analysis.py` - soundfile + numpy silence analysis
- `tests/integration/test_audio_golden.py` - the 15 goldens pinning the swap
- `tests/unit/test_audio_converter.py` - subprocess seam + argv contract tests
- `tests/unit/test_audio_analysis.py` - dBFS/analysis unit tests
- `.github/workflows/ci.yml` - 3.13 must-pass matrix (bridge deleted)
