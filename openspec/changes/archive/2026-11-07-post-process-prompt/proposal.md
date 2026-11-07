# Proposal

## Why

Dictated transcripts are raw speech: disfluent, inconsistently cased, and often missing punctuation. Users already have transcript history in SQLite, but turning the latest transcript into a summary, a rewrite, or a translation currently requires manually copying it into another tool. The clipboard is not a reliable source (the user may have copied something else since dictating), and transcript history has no transformation path. A one-key action that reads the newest completed transcript, runs it through a prompt against a chat model, and returns the result closes that loop without re-recording anything.

## What Changes

- Add a `whisper-dictate process` CLI subcommand with three prompt entry paths: scriptable `--prompt "..."`, an interactive `rofi -dmenu -p "Prompt:"` popup with `dmenu` fallback, and a `POST_PROCESS_PROMPT` environment preset (used to prefill the popup and as a headless fallback).
- Read the target text from the newest completed transcript in SQLite (newest row whose `text` is non-empty), not from the clipboard. Empty transcripts written by silence detection are skipped.
- Guard the trigger: if a recording is in progress, notify and do nothing; if no eligible transcript exists, notify and do nothing without crashing.
- Add a dedicated `POST_PROCESS_PROVIDER` / `POST_PROCESS_MODEL` / `POST_PROCESS_BASE_URL` / `POST_PROCESS_API_KEY` / `POST_PROCESS_TIMEOUT` configuration block. It **MUST NOT** read `WHISPER_MODEL` or any other `WHISPER_*` value; `whisper-1` is a transcription model and is invalid for chat completions.
- Add an OpenAI-compatible chat-completions processor that applies the prompt to the transcript and returns processed text.
- Persist the result as `processed_text` plus prompt/model metadata on the same transcript row, leaving the original `text` untouched. Re-running the command overwrites the processed fields on that row.
- On success, replace the clipboard with the processed text and show a preview in a dunst notification. On API failure, show an error notification and leave both the clipboard and the database unchanged.
- Install a `$mod+p` i3 binding for the interaction through `setup_i3.sh`, idempotently: detect an existing whisper-dictate process binding instead of duplicating it, and refuse to overwrite an unrelated `$mod+p` binding.
- Document the new block in `.env.example` and the README.

## Capabilities

### New Capabilities

- `post-processing`: End-to-end behavior of processing the latest transcript with a user prompt — trigger guards, prompt acquisition (flag, environment preset, rofi/dmenu), chat-model request contract, clipboard/notification output, and idempotent keybinding installation.

### Modified Capabilities

- `configuration`: Add the `POST_PROCESS_*` configuration block, its isolation from `WHISPER_*` transcription settings, lazy validation, and documented defaults.
- `database`: Add schema version 3 processed-text columns, the newest-non-empty-transcript query, and the overwrite/immutability rules for processed versus raw text.

## Impact

- `src/whisper_dictate/config.py`: new `PostProcessConfig`, env loader, and lazy validator.
- `src/whisper_dictate/post_processor.py` (new): chat-completions client, request composition, and provider-agnostic error type.
- `src/whisper_dictate/cli.py`: new `process` command, prompt acquisition, guard checks, and output orchestration.
- `src/whisper_dictate/database.py`: schema version 3 migration, `get_latest_processable_transcript()`, `set_processed_transcript()`.
- `src/whisper_dictate/notifications.py`: processed-text preview and no-transcript/recording-in-progress notifications.
- `setup_i3.sh`: idempotent `$mod+p` binding installation with conflict detection.
- `.env.example`, `README.md`: configuration and usage documentation.
- `tests/unit/`, `tests/integration/`: config isolation, migration, query ordering, processor contract, CLI paths, and keybinding idempotency tests.
- No new runtime dependency: the existing `openai` SDK is used for chat completions.
