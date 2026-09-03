# ADR 5: Transcription Provider ABC and Factory

## Status

Accepted (2026-09-02)

## Context

Transcription started as a single concrete Whisper API client. Making the
provider pluggable required a seam that (a) the OpenAI-compatible API and
future local providers both implement, (b) tests can substitute cheaply,
and (c) configuration can select at runtime - without introducing an
interface where only one implementation exists (roadmap principle:
interfaces only at real boundaries).

## Decision

Transcription is an ABC + factory seam:

- `TranscriptionProvider` (ABC in `src/whisper_dictate/transcription.py`)
  defines the provider contract: `transcribe_audio(audio_file)` returning
  a `TranscriptionResult` (text, language, duration, provider,
  silence_detected).
- `OpenAICompatibleProvider`
  (`src/whisper_dictate/providers/openai_compatible.py`) is the first
  implementation: the Whisper-compatible HTTP API client.
- `create_transcriber(config)` is the factory: configuration-driven
  provider selection, returning the `TranscriptionProvider` the user
  configured. Services (`DictationService`, and since S4 the toggle's
  delegation flow through it) never import a concrete provider - they
  receive whatever the factory builds.
- Provider contract tests (`tests/contract/test_openai_compatible.py`) are
  authoritative for behavior any provider must honor (P11 resolution:
  the provider seam tests live in `tests/contract/`; the TranscriptionResult
  and TranscriptionError unit tests stay in `tests/unit/`).
- This seam is the designated extension point for a future local
  whisper.cpp provider (P14) as the second ABC instance; plugin/entry-point
  discovery (P15) stays closed until a third provider is actually wanted.

## Consequences

- **Positive**: A second provider is a new ABC implementation + a factory
  branch - no service changes
- **Positive**: Tests substitute providers without patching HTTP clients
- **Positive**: Provider behavior is pinned by contract tests, not by
  call-site expectations
- **Negative**: The ABC must stay honest: adding capabilities to one
  provider tempts base-class bloat (mitigated: contract tests fail loudly
  on drift)

## Related Files

- `src/whisper_dictate/transcription.py` - TranscriptionProvider ABC, TranscriptionResult, create_transcriber factory
- `src/whisper_dictate/providers/openai_compatible.py` - OpenAICompatibleProvider
- `tests/contract/test_openai_compatible.py` - authoritative provider contract tests (P11)
