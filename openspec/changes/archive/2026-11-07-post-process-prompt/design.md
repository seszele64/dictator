# Design

## Context

See `proposal.md` for motivation. Current constraints that shape the approach:

- `AppConfig` is constructed eagerly by the CLI group callback (`load_config()` in `src/whisper_dictate/config.py`), so any required `POST_PROCESS_*` field would break unrelated commands such as `info` and `history list`. Transcription API-key validation is already lazy for the same reason (`validate_api_key()`).
- `Database` owns schema versioning (`CURRENT_SCHEMA_VERSION = 2`), migrations guarded by `PRAGMA table_info`, and strict row-to-dict mapping (`_row_to_dict`). Transcripts are written by `DictationService` with raw `text` and `model_used`; silence detection stores an empty `text` row.
- The CLI is a click group in `src/whisper_dictate/cli.py`; per-command database access comes from `@with_database` (`src/whisper_dictate/cli_helpers.py`).
- Active recording state is exposed by `toggle.is_recording(config)` (database `state` key `is_recording` with a legacy file fallback).
- Clipboard writes go through `ClipboardManager.copy_to_clipboard()`; notifications go through `src/whisper_dictate/notifications.py` (`dunstify`).
- `setup_i3.sh` already normalizes and de-duplicates the `$mod+t` binding with `sed` plus an `awk` pass; the new binding should follow the same pattern.

## Goals / Non-Goals

**Goals:**

- One explicit invocation path for prompt-driven post-processing with deterministic guard, cancellation, success, and failure outcomes.
- Total separation between transcription settings and chat settings, enforced by construction rather than documentation.
- Raw transcript immutability and idempotent reprocessing.
- Testable seams: prompt acquisition, model client, clipboard, notifications, and shell binding installation are each mockable.

**Non-Goals:**

- Automatic post-processing after dictation, batch processing of multiple transcripts, or conversation/multi-turn prompting.
- Streaming responses, model discovery, or provider-specific chat APIs beyond OpenAI-compatible `chat/completions`.
- A GUI beyond rofi/dmenu, prompt history, or editing the raw transcript.
- Changing existing dictation, transcription, `history list`, or notification behavior; `history show` gains an additive processed block only.
- Backfilling processed values for historical transcripts.

## Decisions

### Decision: Separate `post_processor.py` module instead of extending the transcription provider

Add `src/whisper_dictate/post_processor.py` with:

- `PostProcessError(Exception)` — provider-agnostic failure wrapper, mirroring `TranscriptionError`.
- `PostProcessor` — constructed from a resolved chat configuration; `process(text: str, prompt: str) -> str`.
- `create_post_processor(config: PostProcessConfig) -> PostProcessor` — resolves base URL and API key, constructs `openai.OpenAI(api_key=..., base_url=..., timeout=config.timeout)`, and returns the processor.

The client is built once per invocation with the resolved timeout, so `POST_PROCESS_TIMEOUT` bounds connect, read, and total request time instead of the SDK's implicit default:

```python
client = OpenAI(api_key=effective_key, base_url=effective_base_url, timeout=config.timeout)
```

The request is:

```python
client.chat.completions.create(
    model=config.model.strip(),
    messages=[
        {"role": "system", "content": prompt},
        {"role": "user", "content": text},
    ],
)
```

The response is `choices[0].message.content`; strip it; raise `PostProcessError` when it is empty/whitespace. Because `config.model` is stripped both here and at persistence, a padded value never reaches the provider or the stored `processed_model`. No `temperature`, `max_tokens`, or streaming parameters are set, so provider defaults apply. For `local` with no key, pass the same `"not-needed"` dummy key used by `create_transcriber()`.

**Why:** `transcription.py` is an audio-file abstraction (`transcribe_audio(Path)`); chat completion is a different request/response contract. Reusing it would either break the `TranscriptionProvider` interface or leak audio concepts into text processing. A dedicated module keeps error types and tests focused.

**Alternatives considered:** adding `process_text()` to `OpenAICompatibleProvider` (rejected: violates its single responsibility and the provider contract tests), or calling the OpenAI SDK directly from the CLI (rejected: untestable and duplicates key/base-URL resolution).

### Decision: Dedicated `PostProcessConfig` with lazy validation

Add to `config.py`:

```python
class PostProcessConfig(BaseModel):
    provider: str = "openai"
    model: str = ""
    base_url: str | None = None
    api_key: str = ""
    timeout: float = 60.0
    prompt: str = ""

def _load_post_process_config_from_env() -> PostProcessConfig: ...
def validate_post_process_config(config: PostProcessConfig) -> None: ...
```

`AppConfig` gains `post_process: PostProcessConfig = Field(default_factory=_load_post_process_config_from_env)`. The loader reads only `POST_PROCESS_PROVIDER`, `POST_PROCESS_MODEL`, `POST_PROCESS_BASE_URL`, `POST_PROCESS_API_KEY`, `POST_PROCESS_TIMEOUT`, and `POST_PROCESS_PROMPT`. It never references a `WHISPER_*` variable. `POST_PROCESS_TIMEOUT` is parsed defensively — `float()` inside `try/except`, then a `> 0` check — so a non-numeric value (`abc`), `0`, or a negative value falls back to `60.0` with a warning naming the variable, because the loader runs during `AppConfig` construction and must not make unrelated commands fail. The resolved value is the one passed to `OpenAI(..., timeout=...)`; there is no second timeout source and no per-request override.

`validate_post_process_config()` is called by the `process` command, not by a Pydantic validator. It evaluates in this fixed order and reports only the first failure, so an error always names the earliest missing setting:

1. `model.strip()` is non-empty → otherwise `ValueError` naming `POST_PROCESS_MODEL` and explaining that `whisper-1` is a transcription model.
2. `provider` resolves through the existing `_resolve_provider_enum()`; unknown values become `custom`.
3. Effective base URL = `config.base_url` or `PROVIDER_DEFAULTS[provider]["base_url"]`; `custom` requires a non-empty result.
4. Effective API key = `config.api_key` or the provider's declared key env var (`OPENAI_API_KEY`, `GROQ_API_KEY`, ...). `local`/`custom` are keyless; auth providers require a key.

Because `PROVIDER_DEFAULTS[WhisperProvider.CUSTOM]["base_url"]` is `None`, step 3 forces an explicit `POST_PROCESS_BASE_URL` for `custom`; `local` resolves `http://localhost:8000/v1` and passes step 4 keyless. `POST_PROCESS_PROVIDER=bogus` therefore becomes `custom` and fails at step 3 when no base URL is set — never at the model step, which has already passed.

**Why lazy:** every CLI invocation builds `AppConfig`; a required field or model validator would turn a missing chat model into a global startup failure and break existing commands and their tests. Lazy validation matches the existing transcription-key pattern and keeps the error scoped to the feature.

**Why no default model:** chat model ids differ per provider and change over time. A guessed default would silently pick a stale or invalid model; requiring `POST_PROCESS_MODEL` guarantees no fallback to `WHISPER_MODEL` and produces an actionable error. `.env.example` supplies `gpt-4o-mini` as an example for OpenAI.

**Hard ban on the provider-table model:** `validate_post_process_config()` and `create_post_processor()` **MUST NOT** call `_resolve_model()` or read `PROVIDER_DEFAULTS[...]["default_model"]`. Those entries are transcription ids (`whisper-1`, `whisper-large-v3`, `microsoft/mai-transcribe-2`); substituting one would send an audio model to a chat endpoint and silently defeat isolation. The only model value used is `config.model.strip()`, and a test asserts that an empty model never reaches `chat.completions.create` for any provider.

**Why reuse `PROVIDER_DEFAULTS` for base URL and key env var:** these are provider facts shared by transcription and chat endpoints, not transcription-specific model settings. Reusing them avoids a second provider table drifting. The `default_model` key is deliberately excluded from reuse (see above).

**Alternatives considered:** a separate chat-provider table with model defaults (rejected: unverified ids, duplicate provider facts), inheriting `WHISPER_API_KEY` (rejected: violates the isolation requirement), or failing at `AppConfig` construction (rejected: breaks unrelated commands).

### Decision: Prompt acquisition lives in `prompting.py`

Add `src/whisper_dictate/prompting.py`:

```python
class PromptUnavailableError(Exception): ...

def acquire_prompt(explicit: str | None, preset: str) -> str | None: ...
```

- Non-empty `explicit` (stripped) returns immediately; no subprocess. An empty or whitespace-only `--prompt` is treated as not supplied.
- Otherwise, if `rofi` is on `PATH`, run `rofi -dmenu -p "Prompt:"`, adding `-filter <preset>` when `preset` is non-empty.
- Else, if `dmenu` is on `PATH`, run `dmenu -p "Prompt:"` with an empty stdin; when `preset` is non-empty, write the preset to stdin as the single entry.
- Else, if `preset` is non-empty, return it without a popup.
- Else raise `PromptUnavailableError`.

Launcher semantics were verified against the installed binaries (`rofi 2.0.0`, `dmenu 5.4`) under Xvfb:

- `rofi -dmenu -filter "Rewrite"` places "Rewrite" in the **input bar** and Enter returns it; typing `" formally"` yields `"Rewrite formally"`. This is a true editable prefill, and `-filter` is the documented flag (`man rofi`: "Filter the list by setting text in input bar to filter").
- `dmenu` has no prefill flag. With empty stdin, typed text is returned by Enter (free-text entry works). With the preset piped on stdin, the preset is the only list entry: Enter accepts it verbatim, while typing replaces the filter and dmenu returns the typed text. That is an accept-or-replace entry, **not** an editable prefill, and the README/design say so explicitly instead of implying parity.

A non-zero launcher exit (Escape) or empty/whitespace stdout returns `None`, which the command treats as silent cancellation. A timeout is different: the module uses `shutil.which` and `subprocess.run` with `capture_output=True`, `text=True`, `shell=False`, and `timeout=10`, and a `subprocess.TimeoutExpired` is wrapped in `PromptUnavailableError` so the CLI notifies and exits 1 rather than pretending the user cancelled. The 10-second bound exists so a wedged launcher cannot hang the command; it is not a user-facing prompt budget.

**Why argv lists and `shell=False`:** the preset originates from `.env`, which is user-controlled text. Passing it as an argv element and writing it to stdin avoids any shell parsing, quoting, or injection surface; no `os.system`/`shell=True` path is permitted.

**Why a separate module:** the launcher/fallback matrix and cancellation semantics are the most failure-prone part of the feature; isolating them allows subprocess mocking in unit tests without building a click runner around each case.

**Alternative considered:** inline in `cli.py` (rejected: coverage and test complexity), or using `rofi` only (rejected: the user requires a dmenu fallback).

### Decision: Schema version 3 stores processed output as nullable columns on `transcripts`

`database.py` changes:

- `CURRENT_SCHEMA_VERSION = 3`.
- `_create_schema()` adds `processed_text TEXT`, `processed_prompt TEXT`, `processed_model TEXT`, `processed_at TEXT` to the `transcripts` table (all nullable, no defaults).
- `_run_migration(3)` reads `PRAGMA table_info(transcripts)` and executes `ALTER TABLE transcripts ADD COLUMN <name> TEXT` only for missing columns. The existing legacy path (unversioned → baseline 1 → current) therefore runs migration 2 then 3.
- `get_latest_processable_transcript() -> dict[str, Any] | None`:

  ```sql
  SELECT * FROM transcripts
  WHERE TRIM(text, ' ' || char(9) || char(10) || char(13) || char(12) || char(11)) <> ''
  ORDER BY timestamp DESC, id DESC
  LIMIT 1
  ```

  Mapped with the explicit column list (including the new columns).

- `set_processed_transcript(transcript_id, processed_text, prompt, model) -> bool`:

  ```sql
  UPDATE transcripts
  SET processed_text = ?, processed_prompt = ?, processed_model = ?,
      processed_at = datetime('now')
  WHERE id = ?
  ```

  Returns `rowcount > 0`. It deliberately does not touch `text` or `updated_at`.

- Every `SELECT *`-based transcript reader (`get_transcript`, `get_transcript_by_recording`, `list_transcriptions`, `get_transcription_with_recording`) gains the four column names **in this same change**. `_row_to_dict` uses `dict(zip(columns, row, strict=True))`, so a reader whose explicit list is shorter than the migrated row width raises `ValueError` on read. Migration and reader updates are an atomic obligation, not two tasks that can land separately.

**Why nullable columns instead of a `processed_transcripts` table:** the relationship is 1:1 and lifecycle-bound to the transcript; a separate table adds a join to every history read and a second delete path. Nullable columns express "not processed yet" directly and keep the overwrite semantics to one UPDATE.

**Why the explicit whitespace set:** plain `TRIM(text)` in SQLite strips only spaces, so a `"\t"` or `"\n"` row would be treated as processable and sent to the provider as empty content. The six-character set (`space`, `\t`, `\n`, `\r`, `\f`, `\v`) matches Python's ASCII whitespace, and the Python-side guard uses the same literal set (`.strip(" \t\n\r\f\v")`) so the SQL and Python layers cannot disagree. Note this deliberately excludes Unicode spaces: those are rare in transcripts and adding them would require a Python-side scan of every row, so the query keeps one SQL predicate.

**Why `timestamp DESC, id DESC`:** SQLite timestamps have second precision, and multiple transcripts can share a second; id makes selection deterministic and matches insertion order.

**Why not update `updated_at`:** `updated_at` currently tracks edits to the raw transcript. Changing it on processing would make history edits look newer and conflate two kinds of mutation; `processed_at` is the processing timestamp.

**Stale-after-edit policy: keep, do not clear.** When `update_transcript()` edits raw text, the processed columns keep their values. Clearing them would destroy the only record of a result the user may still want, and silently un-processing a row is a surprising side effect of an edit command. Staleness is instead *derived*: both `updated_at` and `processed_at` come from `datetime('now')` (UTC, `YYYY-MM-DD HH:MM:SS`), so `updated_at > processed_at` is a valid lexicographic comparison. `history show` renders the warning from that comparison; no extra column or migration is needed, and reprocessing naturally refreshes `processed_at` past `updated_at`.

### Decision: Database migrations stay additive and code-revert safe

Migration 3 only adds nullable columns. If the application is rolled back to a version that predates the feature, the extra columns are ignored by old code, so no down-migration is required. The migration is guarded per column, so partial or repeated runs are safe.

### Decision: The process command orchestrates guards in a fixed order

`@cli.command() process` with `--prompt TEXT`, decorated with `@with_database`:

1. Read `config` from `ctx.obj`.
2. If `toggle.is_recording(config)` → `notify_processing_skipped("Stop recording first.")`; `ctx.exit(1)`.
3. `db.get_latest_processable_transcript()`; if `None` → `notify_processing_skipped("No transcript to process.")`; `ctx.exit(1)`.
4. `validate_post_process_config(config.post_process)`; on `ValueError` → `notify_error(str(e))`; `ctx.exit(1)`.
5. `prompt = acquire_prompt(explicit, config.post_process.prompt)`.
   - `None` → silent `ctx.exit(0)`.
   - `PromptUnavailableError` → `notify_error(...)`; `ctx.exit(1)`.
6. `effective_model = config.post_process.model.strip()` — computed once and used for the client, the database write, and any log line, so a padded value cannot reach either sink.
7. `processed = create_post_processor(config.post_process).process(transcript["text"], prompt)`; on `PostProcessError`/provider error → `notify_error(...)`; `ctx.exit(1)`.
8. `db.set_processed_transcript(transcript["id"], processed, prompt, effective_model)`.
9. `copied = clipboard.copy_to_clipboard(processed)`; `notify_processed(processed, clipboard_copied=copied)`.
10. `ctx.exit(0 if copied else 1)`.

**Why guard recording before the popup:** opening a prompt and only then refusing is a poor interaction and makes the "do nothing" guarantee harder to verify. The guard is a snapshot, not a lock: `toggle.is_recording()` is read once, and a recording started afterwards does not abort the in-flight run. That TOCTOU window is accepted because the command is interactive and user-triggered, and because the alternative (a lock held across a network call) would block dictation itself. This is documented in the spec as an advisory guard rather than papered over.

**Why select the transcript before prompt entry:** "no transcript" is a common empty-state and should not make the user type a prompt first. Configuration validation happens before the popup so a static misconfiguration fails without user effort.

**Ordering nuance:** the database write happens before the clipboard copy. If the clipboard fails, the processed result is still persisted and previewed, matching the spec's no-rollback rule, but the command exits non-zero so scripts can detect the delivery failure. Exactly one notification is shown in that case — `notify_processed(preview, clipboard_copied=False)` — so the user is not shown a success toast followed by a second error toast.

**Alternative considered:** process first, then prompt (nonsensical), or prompt before transcript lookup (worse empty-state UX).

### Decision: Notifications use purpose-specific helpers

Add to `notifications.py`:

- `notify_processing_skipped(reason: str) -> bool` — summary `"Post-processing"`, body `reason`, urgency `normal`, short timeout.
- `notify_processed(text_preview: str, *, clipboard_copied: bool = True) -> bool` — summary `"Processed"`, urgency `normal`, timeout 5000 ms.
  - `clipboard_copied=True`: body is the preview truncated to 200 characters plus `"…"` when longer.
  - `clipboard_copied=False`: body is that preview, a blank line, and the exact line `⚠️ Clipboard copy failed. Result saved to history.`

Error paths reuse the existing `notify_error()`. All notification helpers remain best-effort (return `False` on failure) and never raise; notification failure cannot roll back the database or clipboard.

**Why one helper with a flag instead of a second notification:** two sequential toasts (preview + error) overlap on i3/dunst and the second can be mistaken for the first. The flag keeps one call site, one toast, and an exact body string that a CLI test can assert.

**Why a 200-character preview:** enough to verify the transformation without covering the screen; consistent with the existing short bodies and easy to assert in tests. Only the preview is truncated — the fixed failure line is always intact.

### Decision: `history show` gains an additive processed block; `history list` is untouched

`show_history()` prints, immediately after the existing transcript block, when `processed_text` is non-null and non-empty:

```text
============================================================
🧠 Processed
============================================================

<processed text, verbatim>

🧾 Prompt: <processed_prompt or "(not recorded)">
🤖 Processed with: <processed_model or "(not recorded)">
🕒 Processed at: <processed_at or "(not recorded)">
```

Then, only when `updated_at` is non-null and greater than `processed_at`, one warning line:

```text
⚠️  Raw transcript was edited after this processing; the result may be stale. Reprocess to refresh.
```

Rules pinned for tests:

- **Empty state:** when `processed_text` is `None` or empty after `.strip()`, print nothing new — no heading, no fields, no warning. An unprocessed transcript's output stays byte-identical to the current format, which is what makes this additive and regression-testable.
- **Partial metadata:** a column that is null while `processed_text` is set renders `"(not recorded)"` rather than being omitted, so the block's shape is stable.
- **Stale display:** the block is never hidden or emptied because the raw text changed; it is shown with the warning. This matches the "keep, do not clear" storage policy — the UI explains the mismatch instead of the database erasing history.
- **`history list`:** the table and preview stay exactly as today; no new column, no marker. This avoids widening an already 90-character layout.

**Alternative considered:** clear `processed_*` on edit (rejected: destroys results and adds a surprising side effect to an edit command), or add a `processed_stale` column (rejected: derivable from two existing timestamps, and another migration for a display detail).

### Decision: i3 binding installation mirrors the existing normalize-and-protect pattern

`setup_i3.sh` gains:

- `PROCESS_CMD="$REPO_ROOT/.venv/bin/whisper-dictate process"` or `"whisper-dictate process"` fallback, chosen the same way as `TOGGLE_CMD`.
- Canonical line: `bindsym $mod+p exec --no-startup-id $PROCESS_CMD`.
- **Normalize** existing whisper-dictate process lines (matching `whisper-dictate` plus a `process` argument, or the legacy `post-process-prompt` shim) to the canonical line with `sed -E`, using an anchored pattern: `s#^[[:space:]]*bindsym[[:space:]].*(whisper-dictate[[:space:]]+process|post-process-prompt).*$#<canonical>#`.
- **Deduplicate** canonical lines with the same `awk` exact-line comparison used for `$mod+t` (comments and blank lines pass through verbatim).
- **Conflict check before appending:** if an active, non-comment `$mod+p` (or `Mod4+p` / `Super+p`) binding exists that does not reference the process command, print a warning with the line to add manually and leave the config unchanged.
- Append the canonical line only when no `$mod+p` binding exists.

Comment handling is explicit rather than incidental: a line is treated as a binding only when its first non-whitespace token is `bindsym` (`^[[:space:]]*bindsym[[:space:]]`). Because `#` is i3's comment character, `# bindsym $mod+p exec whisper-dictate process`, `\t#bindsym $mod+p ...`, and indented comments can never match: after the leading whitespace the next character is `#`, not `bindsym`. Those lines are therefore never rewritten, never collapsed as duplicates, and never counted as an existing binding or a conflict — so the canonical active line is still appended once. The same anchored pattern is used by the conflict `grep -Eq`, so a commented-out unrelated `$mod+p` binding does not block installation either.

Leading whitespace before an active `bindsym` *is* matched (i3 tolerates indentation), which the previous `^bindsym`-only `sed` would have duplicated instead of normalizing.

**Why refuse instead of overwrite:** i3 resolves duplicate keys by last-binding-wins, so appending would silently disable the user's command. The spec requires non-clobbering; a warning plus manual instruction is the only safe default.

**Alternatives considered:** always append (rejected: clobbers), use a different key (rejected: the user specified `Meta+P`), or install through `i3-msg` (rejected: not a config mutation mechanism).

## Security and privacy boundaries

These are implementation constraints, not aspirations; each has a spec scenario and a test.

- **Secrets in memory only.** The effective API key is resolved inside `create_post_processor()` and passed to `openai.OpenAI`. It is never written to `PostProcessConfig` copies, log records, notifications, `processed_*` columns, or exception text. `validate_post_process_config()` names variables (`POST_PROCESS_API_KEY`, `OPENAI_API_KEY`), never values.
- **Transcript exposure is bounded.** The full transcript is sent only to the configured chat endpoint. Locally it is written to the `transcripts.text` column that already existed; the only UI exposure is the `notify_processed` preview, capped at 200 characters plus an ellipsis. `history show` prints processed text because the user explicitly asked for that record; prompts are printed because the user wrote them.
- **Errors are message-shaped.** `PostProcessError` carries a short user-facing string. The CLI notifies `str(e)` and never formats a traceback into a notification; tracebacks that reach the log file go through the existing logger path with `logger.exception` only where the project already does so, and never include the API key (the SDK does not echo it in `APIStatusError`).
- **No shell.** Launchers run via `subprocess.run([...], shell=False, capture_output=True, text=True, timeout=10)`; the preset goes to stdin for dmenu and as an argv element for `-filter`, so `.env` content cannot become shell syntax. No `os.system`, `shell=True`, or string interpolation into a command line is permitted anywhere in `prompting.py`.
- **Nothing new is logged at INFO for content.** New log lines record counts, provider name, model, timeout, and outcome — not prompt text or output text.

## Data Flow

```text
$mod+p / whisper-dictate process [--prompt TEXT]
            │
            ▼
   CLI group bootstrap() ── load .env ──> AppConfig
            │                         ├── openai:  WHISPER_* (unchanged)
            │                         └── post_process: POST_PROCESS_*
            │                              (timeout: float; abc/0/-5 → 60.0 + warning)
            ▼
   recording? (toggle.is_recording)
      yes ──> notify "Stop recording first." ──> exit 1
      no
            ▼
   db.get_latest_processable_transcript()
      none ─> notify "No transcript to process." ──> exit 1
      found
            ▼
   validate_post_process_config()
      invalid ─> notify_error ──> exit 1
            ▼
   acquire_prompt(--prompt / rofi / dmenu / POST_PROCESS_PROMPT)
      cancelled (Escape / blank) ─> exit 0 (silent)
      timeout (10 s) ─> PromptUnavailableError ─> notify_error ──> exit 1
      unavailable ─> notify_error ──> exit 1
            ▼
   effective_model = POST_PROCESS_MODEL.strip()
   create_post_processor() ──> OpenAI(timeout=config.timeout)
        │                        (POST_PROCESS_TIMEOUT; default 60.0)
        └──> chat.completions.create(
                 model  = effective_model,
                 system = prompt,
                 user   = transcript.text
             )
      error/empty ─> notify_error ──> exit 1 (clipboard and DB untouched)
            ▼
   output = response.strip()
      (one stripped value reused for the DB write, clipboard, and preview)
            ▼
   db.set_processed_transcript(id, output, prompt, effective_model)
            ▼
   copied = clipboard.copy_to_clipboard(output)
   notify_processed(output, clipboard_copied=copied)
      copied=False ─> one toast: preview + "⚠️ Clipboard copy failed. Result saved to history." ──> exit 1
      copied=True  ─> preview toast ──> exit 0
```

## File Changes

- `src/whisper_dictate/config.py`
  - Add `PostProcessConfig` after `WhisperConfig`.
  - Add `_load_post_process_config_from_env()` beside `_load_whisper_config_from_env()`.
  - Add `validate_post_process_config()` beside `validate_api_key()`.
  - Add `post_process: PostProcessConfig` to `AppConfig`.
  - Export the new names used by the CLI/processor; no change to `WHISPER_*` behavior.
- `src/whisper_dictate/post_processor.py` (new)
  - `PostProcessError`, `PostProcessor`, `create_post_processor()`.
  - Resolve base URL/key with `PROVIDER_DEFAULTS` and `_resolve_provider_enum()`; construct `openai.OpenAI(api_key=..., base_url=..., timeout=config.timeout)`.
  - Never read `_resolve_model()` or `PROVIDER_DEFAULTS[...]["default_model"]`; the only model value is `config.model.strip()`.
- `src/whisper_dictate/prompting.py` (new)
  - `PromptUnavailableError`, `acquire_prompt()`.
  - Run launchers with `subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=10)`; a `TimeoutExpired` becomes `PromptUnavailableError`, never `None`.
- `src/whisper_dictate/database.py`
  - `CURRENT_SCHEMA_VERSION = 3`.
  - `_create_schema()` transcript columns.
  - `_run_migration()` case for version 3 with per-column `PRAGMA` guards.
  - `get_latest_processable_transcript()`, `set_processed_transcript()`.
  - Extend `_row_to_dict` column lists in transcript readers so the new fields are visible in history/details.
- `src/whisper_dictate/cli.py`
  - Add `process` command with `--prompt`.
  - Extend `show_history()` (not a new command) to print the additive processed block after the transcript block: verbatim `processed_text`, then prompt/model/timestamp lines with `"(not recorded)"` placeholders, then the stale warning when `updated_at > processed_at`. Print nothing when `processed_text` is null or empty so unprocessed output stays byte-identical.
  - Import `toggle.is_recording`, `validate_post_process_config`, `acquire_prompt`, `create_post_processor`, `ClipboardManager`, and notification helpers.
- `src/whisper_dictate/notifications.py`
  - Add `notify_processing_skipped(reason: str) -> bool` and `notify_processed(text_preview: str, *, clipboard_copied: bool = True) -> bool`.
  - `clipboard_copied=False` appends a blank line plus the exact line `⚠️ Clipboard copy failed. Result saved to history.`; only the preview is truncated at 200 characters, so the failure line is always intact.
- `setup_i3.sh`
  - Add `PROCESS_CMD`, normalization, dedupe, conflict detection, and `$mod+p` append logic.
- `.env.example`
  - Add a commented `POST_PROCESS_*` block after the Whisper provider blocks, documenting `POST_PROCESS_PROVIDER=openai`, `POST_PROCESS_MODEL=` (required; example `gpt-4o-mini`), `POST_PROCESS_BASE_URL=`, `POST_PROCESS_API_KEY=`, `POST_PROCESS_TIMEOUT=60`, `POST_PROCESS_PROMPT=`, and the no-`WHISPER_MODEL`-inheritance rule.
- `README.md`
  - Add a "Post-processing" section: usage (`process --prompt`, Meta+P), prompt sources, the `POST_PROCESS_*` table, exit codes, and the privacy note that the transcript is sent to the configured chat provider.
- `scripts/check_coverage.py`
  - Add floors for the new modules (for example `post_processor.py` 80%, `prompting.py` 80%) once their tests land.
- `tests/unit/test_config.py`, `tests/unit/test_post_processor.py` (new), `tests/unit/test_prompting.py` (new), `tests/unit/test_cli.py`, `tests/unit/test_notifications.py`, the existing database split (`tests/integration/test_database_schema.py`, `tests/integration/test_migration.py`, `tests/integration/test_database_update.py`), `tests/integration/test_setup_i3.py` (new)
  - Cover every spec scenario; mock `openai.OpenAI`, subprocess launchers, clipboard, and notifications.

**Security notes for these files** (each maps to a `Secrets, transcripts, and subprocesses are handled safely` / `Configuration and provider errors never expose secrets` scenario):

- The effective API key is resolved inside `create_post_processor()` only; it is never copied onto a config object, logged, notified, stored in `processed_*`, or interpolated into an exception message. Validation errors name variables (`POST_PROCESS_API_KEY`, `OPENAI_API_KEY`) and never values.
- `prompting.py` uses argv lists and `shell=False` exclusively; the preset reaches rofi as an argv element and dmenu as stdin, so `.env` content is never parsed as shell syntax.
- `notifications.py` caps `notify_processed` exposure at 200 characters plus an ellipsis; the fixed clipboard-failure line is appended after a blank line and is not counted against the preview budget.
- No CLI path formats a traceback into a notification or a log record; provider errors surface as a short user-facing `str(e)`.

## Risks / Trade-offs

- **Sensitive transcripts leave the machine on every invocation** → processing is explicit, never automatic; the README states which provider receives the text; the original transcript stays local either way.
- **The chat model may rewrite meaning rather than clean it** → the raw transcript is immutable, both versions are visible in history, and the user previews the result before pasting.
- **`POST_PROCESS_MODEL` is required, adding setup friction** → the error names the variable and gives a valid example; `.env.example` ships a commented OpenAI example; no invalid default or `whisper-1` can leak in.
- **`POST_PROCESS_*` validation can drift from the provider table** → it reuses `PROVIDER_DEFAULTS` and `_resolve_provider_enum()`; tests cover every provider, including unknown → custom.
- **Schema migration touches a live table** → only nullable columns are added, each guarded by `PRAGMA table_info`; version 2/legacy/fresh paths are tested.
- **Concurrent process invocations race on the same row** → the final single UPDATE wins; no partial state is possible and `processed_at` records the last success. A lock is unnecessary for an interactive, user-triggered action.
- **The recording guard is advisory, so it has a TOCTOU window** → `toggle.is_recording()` is read once, immediately before lookup; a recording started after that check does not abort the in-flight run, and the guard only avoids processing a transcript that is still being written. Holding a lock across the model call would block dictation itself, so the window is accepted and documented as best-effort rather than papered over.
- **A wedged rofi/dmenu process could hang the command** → the launcher runs with a 10 s timeout, and a timeout is a launcher failure (`PromptUnavailableError` → error notification, exit 1), deliberately distinct from Escape/blank-input cancellation (`exit 0`).
- **dmenu has no editable-prefill flag** → with a preset, dmenu receives it on stdin as a single accept-or-replace entry; typing replaces the filter and returns the typed text. Only rofi `-filter` or `--prompt` gives a true editable prefill, and the README states this rather than implying parity.
- **`$mod+p` may already belong to the user** → the installer refuses to overwrite and prints the exact line to add manually; idempotency tests run the script twice against a temp config.
- **Notifications may expose output on screen** → same existing trade-off as transcription previews; the preview is truncated and uses normal urgency.
- **Processed output can go stale after a raw-text edit** → the processed columns are retained (clearing them would destroy the only result), and `history show` renders a warning derived from `updated_at > processed_at`; reprocessing refreshes `processed_at` and clears the warning without a migration.
- **Chat context limits** → an over-long transcript produces a provider 4xx/context-length error, which is notified with exit 1 while the clipboard and every `processed_*` column stay unchanged; no truncation, chunking, or partial result is stored, and chunking is deliberately out of scope.

## Migration Plan

1. Land code, tests, docs, and `setup_i3.sh` together.
2. On the next CLI invocation, `Database.initialize()` migrates any v2/legacy database to v3; no backfill or manual step.
3. Re-run `./setup_i3.sh` to install the `$mod+p` binding. If an unrelated `$mod+p` exists, follow the printed instruction instead.
4. Rollback: reverting the code leaves the nullable v3 columns in place, which older code ignores. No down migration is required.

## Open Questions

None blocking. Resolved during design: rofi `-filter` is a true editable prefill, while dmenu has no prefill flag and therefore treats the preset as an accept-or-replace entry (see "Prompt acquisition lives in `prompting.py`"). Users who want an editable preset should use rofi or pass `--prompt`.
