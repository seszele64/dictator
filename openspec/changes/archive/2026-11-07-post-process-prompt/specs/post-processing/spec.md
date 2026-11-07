# Spec Delta

## Purpose

Turns the most recent completed transcript into prompt-driven output (summary, rewrite, translation) on explicit user request, with the result delivered to the clipboard and persisted without destroying the raw transcript.

## ADDED Requirements

### Requirement: The latest non-empty transcript is the processing input

The system **SHALL** resolve processing input from the newest transcript record whose `text` is non-empty after trimming, ordered by transcript timestamp descending and then id descending, and **MUST NOT** read the clipboard or the audio recording as the input source.

#### Scenario: Newest non-empty transcript wins

- **GIVEN** the database contains transcript A with non-empty text and a newer transcript B with non-empty text
- **WHEN** the user invokes processing
- **THEN** the text sent to the model is transcript B's text

#### Scenario: Newer empty transcripts are skipped

- **GIVEN** the newest transcript row has empty text (for example from silence detection) and an older row has non-empty text
- **WHEN** the user invokes processing
- **THEN** the older non-empty transcript is selected and the empty row is ignored

#### Scenario: Clipboard content is irrelevant

- **GIVEN** the clipboard contains unrelated text and a non-empty transcript exists
- **WHEN** the user invokes processing
- **THEN** the clipboard text is not used as input and is replaced only after a successful model response

#### Scenario: Equal timestamps resolve deterministically

- **GIVEN** two non-empty transcripts share the same timestamp
- **WHEN** the user invokes processing
- **THEN** the row with the greater id is selected

---

### Requirement: Processing is blocked while a recording is in progress

When the application's existing recording-state check reports an active recording, the process command **SHALL** notify the user that recording must stop first and **MUST NOT** read a transcript, call a model, write the database, or change the clipboard.

#### Scenario: Recording in progress is refused

- **GIVEN** a recording is in progress
- **WHEN** the user invokes processing
- **THEN** a notification tells the user to stop recording first
- **AND** no model request is made, no processed fields are written, and the clipboard is unchanged

---

### Requirement: A missing or empty transcript is a handled no-op

When no transcript with non-empty text exists, the process command **SHALL** show a "No transcript to process" notification and terminate without an unhandled exception, model request, database write, or clipboard change.

#### Scenario: Empty history

- **GIVEN** the transcript table has no rows
- **WHEN** the user invokes processing
- **THEN** a "No transcript to process" notification is shown and the command exits cleanly

#### Scenario: Only empty transcripts exist

- **GIVEN** every transcript row has empty text
- **WHEN** the user invokes processing
- **THEN** a "No transcript to process" notification is shown and no row is updated

---

### Requirement: The prompt comes from a flag, a preset, or an interactive launcher

The process command **SHALL** accept a non-empty `--prompt` value as the prompt, otherwise **MUST** open an interactive prompt prefilled with `POST_PROCESS_PROMPT` when available, and **MUST** fall back to `POST_PROCESS_PROMPT` without a popup when no launcher exists.

#### Scenario: Explicit prompt bypasses interaction

- **GIVEN** the user runs `whisper-dictate process --prompt "Summarize this"`
- **WHEN** rofi and dmenu are both installed
- **THEN** no popup opens and "Summarize this" is used as the prompt

#### Scenario: Empty or whitespace-only flag is treated as absent

- **GIVEN** `POST_PROCESS_PROMPT="Rewrite formally"` and rofi is installed
- **WHEN** the user runs `process --prompt ""` or `process --prompt "   "`
- **THEN** the flag is treated as not supplied, the popup opens prefilled with "Rewrite formally", and no cancel path is taken

#### Scenario: rofi is preferred for interaction

- **GIVEN** no `--prompt` is supplied and both rofi and dmenu are installed
- **WHEN** permission to process is required
- **THEN** `rofi -dmenu -p "Prompt:"` is shown and its result is used

#### Scenario: rofi preset uses the documented filter flag

- **GIVEN** `POST_PROCESS_PROMPT="Rewrite formally"` and rofi is installed
- **WHEN** the popup is launched
- **THEN** rofi is invoked as `rofi -dmenu -p "Prompt:" -filter "Rewrite formally"`
- **AND** the input bar text is that preset and remains editable, so typing appends to it and Enter submits the edited value

#### Scenario: dmenu is the fallback launcher

- **GIVEN** no `--prompt` is supplied and rofi is unavailable but dmenu is installed
- **WHEN** the user invokes processing
- **THEN** a dmenu prompt labelled "Prompt:" is shown and its result is used
- **AND** dmenu receives an empty stdin when no preset is set, so typing produces free text that Enter submits

#### Scenario: dmenu preset is an accept-or-replace entry

- **GIVEN** `POST_PROCESS_PROMPT` is non-empty and rofi is unavailable but dmenu is installed
- **WHEN** the dmenu prompt opens
- **THEN** the preset is written to dmenu's stdin as its only entry, so Enter accepts the preset verbatim
- **AND** typing replaces the filter, so dmenu returns the typed text instead (dmenu has no editable-prefill flag; this is documented, not a prefill guarantee)

#### Scenario: Environment preset prefills the popup

- **GIVEN** `POST_PROCESS_PROMPT="Rewrite formally"` and rofi is installed
- **WHEN** the popup opens
- **THEN** "Rewrite formally" is offered as the initial input while remaining editable

#### Scenario: Environment preset works without a launcher

- **GIVEN** `POST_PROCESS_PROMPT` is non-empty and neither rofi nor dmenu is installed
- **WHEN** the user invokes processing without `--prompt`
- **THEN** the preset is used as the prompt without an error notification

#### Scenario: No prompt source is available

- **GIVEN** no `--prompt` is supplied, `POST_PROCESS_PROMPT` is empty, and neither rofi nor dmenu is installed
- **WHEN** the user invokes processing
- **THEN** a dunst error notification explains that rofi/dmenu is required or `--prompt` must be passed
- **AND** no model request is made and the clipboard and database are unchanged

---

### Requirement: Empty or dismissed prompt input cancels silently

When the interactive prompt is dismissed or returns an empty or whitespace-only value, the process command **SHALL** cancel without any notification, model request, database write, or clipboard change. This silent cancellation **MUST NOT** cover a launcher that fails to terminate: a launcher timeout is an error, not a cancellation.

#### Scenario: Escape cancels

- **GIVEN** the interactive popup is open
- **WHEN** the user presses Escape
- **THEN** the command exits with no notification and no side effects

#### Scenario: Blank input cancels

- **GIVEN** the interactive popup is open
- **WHEN** the user submits only whitespace
- **THEN** the command treats the invocation as cancelled and performs no side effects

#### Scenario: A hanging launcher is reported as an error

- **GIVEN** rofi starts but does not exit within 10 seconds
- **WHEN** the process command waits for it
- **THEN** the invocation is treated as a launcher failure with an error notification and exit status 1
- **AND** it is not reported as a silent cancellation, and the clipboard and database are unchanged

---

### Requirement: Processing uses a dedicated openai-compatible chat model

The system **SHALL** send the prompt as the system instruction and the selected transcript as the user message to an OpenAI-compatible chat-completions endpoint configured by the `POST_PROCESS_*` block, **MUST** construct the client with the resolved `POST_PROCESS_TIMEOUT` (`openai.OpenAI(..., timeout=config.timeout)`), and **MUST** return only the first choice's text content with surrounding whitespace removed.

#### Scenario: Request carries prompt and transcript separately

- **GIVEN** the prompt "Translate to German" and the transcript "hello world"
- **WHEN** processing runs
- **THEN** the request contains the prompt as the system message and the transcript as the user message

#### Scenario: Request uses the configured timeout

- **GIVEN** `POST_PROCESS_TIMEOUT=15` and a successful response
- **WHEN** `create_post_processor()` builds the client
- **THEN** `openai.OpenAI` is constructed with `timeout=15.0` and the request inherits that bound

#### Scenario: Request model is the stripped configured model

- **GIVEN** `POST_PROCESS_MODEL="  gpt-4o-mini  "`
- **WHEN** processing runs
- **THEN** `chat.completions.create` receives `model="gpt-4o-mini"`

#### Scenario: Model output is trimmed

- **GIVEN** the chat model returns `"  Hello world.  "`
- **WHEN** processing succeeds
- **THEN** the stored, clipboard, and notification text is `"Hello world."`

#### Scenario: Empty model output is a failure

- **GIVEN** the chat model returns empty or whitespace-only content
- **WHEN** processing runs
- **THEN** the invocation is treated as an API failure and no success output is produced

---

### Requirement: Successful processing replaces the clipboard and previews the result

On a successful model response, the system **SHALL** replace the clipboard contents with the processed text, persist the processed text plus the exact prompt and the stripped effective model on the source transcript row, and show a dunst notification containing a preview of the processed text.

#### Scenario: Clipboard, database, and notification are updated

- **GIVEN** a successful model response of "Clean output"
- **WHEN** processing completes
- **THEN** the clipboard contains "Clean output"
- **AND** the source transcript row stores "Clean output" as processed text with the exact prompt used and the stripped effective model
- **AND** a notification shows a preview of "Clean output"

#### Scenario: Padded model is stored stripped

- **GIVEN** `POST_PROCESS_MODEL=" gpt-4o-mini "` and a successful response
- **WHEN** the result is persisted
- **THEN** `processed_model` is `gpt-4o-mini` and no whitespace variant is written

#### Scenario: Clipboard failure does not roll back persistence

- **GIVEN** the model succeeds but no clipboard tool can copy the result
- **WHEN** processing completes
- **THEN** the processed text is still persisted and previewed
- **AND** the single notification is produced by `notify_processed(preview, clipboard_copied=False)`, whose body is `<preview>` followed by a blank line and `⚠️ Clipboard copy failed. Result saved to history.`
- **AND** the command exits non-zero

---

### Requirement: History display surfaces processed output without replacing the raw text

`history show` **SHALL** render a processed block after the transcript block when `processed_text` is non-empty, showing the processed text, prompt, model, and processing timestamp. When `processed_text` is null or empty the block **MUST** be omitted and unprocessed output **MUST** remain byte-identical to the current format. When `updated_at` is later than `processed_at`, the block **SHALL** show a staleness warning because processed values are retained rather than cleared.

#### Scenario: Processed row shows all four fields

- **GIVEN** a transcript whose processed text is "Hello there.", prompt "Clean up", model "gpt-4o-mini", and `processed_at` "2026-11-07 10:00:00"
- **WHEN** the user runs `history show <id>`
- **THEN** the output contains a processed section with "Hello there.", "Clean up", "gpt-4o-mini", and "2026-11-07 10:00:00"
- **AND** the raw transcript text is still shown unchanged above it

#### Scenario: Unprocessed row has no processed block

- **GIVEN** a transcript whose `processed_text` is null or empty
- **WHEN** the user runs `history show <id>`
- **THEN** no processed heading, prompt line, model line, or timestamp line is printed
- **AND** the rest of the output matches the pre-change format

#### Scenario: Edited-after-processing row is marked stale

- **GIVEN** a transcript processed at "2026-11-07 10:00:00" whose raw text was edited at "2026-11-07 11:00:00"
- **WHEN** the user runs `history show <id>`
- **THEN** the processed block is still displayed with its stored values
- **AND** a warning states that the raw transcript was edited after processing and the result may be stale

---

### Requirement: Failures leave the clipboard and database untouched

When configuration validation, the model request, or response handling fails, the system **SHALL** show an error notification and **MUST NOT** change the clipboard or write any processed field; any previously stored processed text **MUST** remain intact.

#### Scenario: Provider error preserves prior state

- **GIVEN** a transcript row already has processed text "Old result" and the chat provider returns an error
- **WHEN** processing fails
- **THEN** an error notification is shown
- **AND** the row still contains "Old result"
- **AND** the clipboard is unchanged

#### Scenario: Missing chat configuration fails before any request

- **GIVEN** `POST_PROCESS_MODEL` is empty
- **WHEN** the user invokes processing
- **THEN** an actionable error notification is shown, no request is sent, and the clipboard and database are unchanged

#### Scenario: Oversized transcript yields an API failure with no side effects

- **GIVEN** a transcript long enough for the provider to reject the request with a context-length or 4xx error
- **WHEN** processing runs
- **THEN** an error notification is shown, the command exits non-zero, and the clipboard and every `processed_*` column are unchanged
- **AND** no truncation, chunking, or partial result is stored

#### Scenario: Provider error text never leaks secrets or tracebacks

- **GIVEN** the provider returns an authentication error while `POST_PROCESS_API_KEY` is set
- **WHEN** the failure is notified and logged
- **THEN** the message names the failure category without echoing the key value, the transcript body, or a Python traceback

---

### Requirement: The recording guard is advisory and processing is explicit

The recording check **SHALL** read the application's existing recording state once, immediately before transcript lookup, and **MUST NOT** rely on that snapshot to prevent a recording that starts afterwards: a recording that begins between the check and the database write does not cancel processing, and the guard's purpose is to avoid processing a transcript that is still being written.

#### Scenario: A recording starting after the guard does not abort processing

- **GIVEN** `toggle.is_recording()` reports `False` and the user starts recording after the guard has passed
- **WHEN** the model call and database write complete
- **THEN** processing still finishes and persists its result
- **AND** the behavior is documented as a best-effort guard rather than a lock

---

### Requirement: Exit status distinguishes success, cancellation, and refusal

The process command **SHALL** exit `0` after a successful processing or a silent user cancellation, and **MUST** exit non-zero when a recording blocks the request, no transcript exists, no prompt source is available, configuration is invalid, or the model/copy step fails.

#### Scenario: Success exits zero

- **GIVEN** a valid transcript, prompt, and model configuration
- **WHEN** processing succeeds
- **THEN** the command exits `0`

#### Scenario: Refusal exits non-zero

- **GIVEN** a recording is in progress
- **WHEN** the user invokes processing
- **THEN** the command exits non-zero after showing the stop-recording notification

#### Scenario: Cancellation exits zero

- **GIVEN** the interactive prompt is dismissed
- **WHEN** the command returns
- **THEN** the command exits `0`

---

### Requirement: Secrets, transcripts, and subprocesses are handled safely

The system **SHALL** invoke external launchers through `subprocess.run` with an argv list and no shell (`shell=False`), **MUST NOT** write the chat API key, the full transcript, or a traceback to the log database, log file, notification, or terminal, and **MUST** limit transcript exposure to the `notify_processed` preview (at most 200 characters plus ellipsis). Provider errors **MUST** be surfaced as a short user-facing message.

#### Scenario: Launchers are executed without a shell

- **GIVEN** rofi and dmenu are both available
- **WHEN** `acquire_prompt()` runs a launcher
- **THEN** the command is passed as an argv list to `subprocess.run` with `shell=False` and `capture_output=True`
- **AND** no preset, prompt, or path is interpolated into a shell string

#### Scenario: Logs and notifications carry no key or full transcript

- **GIVEN** a processing attempt on a long transcript with a configured API key
- **WHEN** the attempt fails
- **THEN** no log record, notification body, or exception message contains the API key value or the full transcript text

#### Scenario: Unexpected exceptions are reduced to a message

- **GIVEN** an unexpected SDK exception with a long traceback
- **WHEN** the CLI catches it
- **THEN** the notification and log entry contain the message summary only, never the traceback text

---

### Requirement: The i3 keybinding is installed idempotently without clobbering

`setup_i3.sh` **SHALL** install a `$mod+p` binding that runs the process command, **MUST** replace or normalize an existing whisper-dictate process binding instead of adding a duplicate, and **MUST NOT** overwrite an unrelated existing `$mod+p` binding.

#### Scenario: First run adds the binding once

- **GIVEN** an i3 config with no `$mod+p` binding
- **WHEN** `setup_i3.sh` runs
- **THEN** exactly one `$mod+p` line invoking the process command is appended

#### Scenario: Re-running does not duplicate

- **GIVEN** the process binding was installed by a previous run
- **WHEN** `setup_i3.sh` runs again
- **THEN** the config still contains exactly one canonical process binding and no duplicate line

#### Scenario: Unrelated binding is preserved

- **GIVEN** the i3 config already binds `$mod+p` to an unrelated command
- **WHEN** `setup_i3.sh` runs
- **THEN** the unrelated line is left unchanged
- **AND** the script reports that the binding was not installed and how to add it manually

#### Scenario: Commented bindings are neither normalized nor counted

- **GIVEN** the i3 config contains `# bindsym $mod+p exec whisper-dictate process` and `\t#bindsym $mod+p exec something-else`
- **WHEN** `setup_i3.sh` runs
- **THEN** both comment lines are left byte-identical
- **AND** neither is treated as an existing process binding nor as a conflict, so the canonical active `$mod+p` line is appended once

#### Scenario: Leading whitespace before bindsym is still recognized

- **GIVEN** the i3 config contains `   bindsym $mod+p exec whisper-dictate process --prompt x`
- **WHEN** `setup_i3.sh` runs
- **THEN** the line is normalized to the canonical binding rather than duplicated
- **AND** normalization only rewrites lines whose first non-whitespace token is `bindsym`

---

### Requirement: Post-processing behavior is covered by automated tests

The change **SHALL** add automated tests covering transcript selection, both guards, prompt-source precedence and cancellation, launcher timeout as an error, request composition (timeout, stripped model), clipboard/notification output including the failure body, failure isolation, history display of processed and stale rows, migration/overwrite semantics, reader column coverage, configuration isolation from `WHISPER_*` and provider model defaults, and keybinding idempotency with comment lines.

#### Scenario: Test suite exercises every behavior

- **GIVEN** unit, integration, and CLI tests added by this change
- **WHEN** `uv run pytest` runs
- **THEN** every requirement above has at least one passing scenario-level test, with external model and desktop-tool calls mocked
