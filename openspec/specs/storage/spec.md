# storage Specification

## Purpose
TBD - created by archiving change fix-storage-safety. Update Purpose after archive.
## Requirements
### Requirement: Recording paths resolve only within the recordings root
The system **SHALL** resolve stored recording paths by joining the stored path onto the configured recordings root, normalizing the result, and verifying it remains inside the recordings root, and **MUST NOT** read, play, or unlink any file outside the recordings root — including paths that are absolute or that traverse upward with `..`.

#### Scenario: Relative path resolves inside the recordings root
- Given: a recording whose stored `file_path` is `2024/03/15/abc.mp3`
- When: the application resolves the path for playback or deletion
- Then: the resolved path is `<recordings_root>/2024/03/15/abc.mp3` and it is used normally

#### Scenario: Absolute path outside the recordings root is rejected
- Given: a recording whose stored `file_path` is an absolute path outside the recordings root (e.g. `/etc/example.mp3`)
- When: the application resolves the path
- Then: the path is rejected with a warning, the file is never accessed, and the recording is treated as having no file

#### Scenario: Parent traversal is rejected
- Given: a recording whose stored `file_path` is `../../outside.mp3`
- When: the application resolves the path
- Then: the resolved path is detected as escaping the recordings root and the file is never read or unlinked

#### Scenario: Legacy absolute path inside the recordings root still works
- Given: a recording whose stored `file_path` is an absolute path that resolves inside the recordings root (legacy data written by the toggle daemon)
- When: the application resolves the path
- Then: the path is normalized and used normally without data loss

---

### Requirement: Empty file paths are treated as absent recordings
The system **SHALL** treat an empty `file_path` (`""`) as the explicit "no file" sentinel for a recording row, and **MUST NOT** resolve it to the recordings root or any other directory.

#### Scenario: Playback of a recording without a file
- Given: a recording row with `file_path=""` (e.g. a silence-only dictation)
- When: the user requests the audio for that recording
- Then: a friendly "no audio file" message is shown instead of a path being constructed or an exception being raised

#### Scenario: Deletion of a recording without a file
- Given: a recording row with `file_path=""`
- When: the user deletes the recording from history
- Then: only the database row is removed; no directory or file is unlinked and no exception is raised

---

### Requirement: Saved audio files are persisted atomically with claim-first ordering
The system **SHALL** persist audio files so the final path only ever contains complete content (stage into a temporary file in the destination directory and finalize with an atomic rename), and **SHALL** update the recording row's `file_path` in the database before the file reaches its final location, rolling the row change back if the finalize fails, so a concurrent `audio cleanup` can never delete a file whose row does not yet claim it.

#### Scenario: Successful save leaves file and row consistent
- Given: a completed recording being saved to persistent storage
- When: `save_audio` finishes successfully
- Then: the row's `file_path` matches the on-disk final path, the file at that path is complete, and no partial or temporary file remains at the final path

#### Scenario: Cleanup cannot delete a file that is being persisted
- Given: a save in progress and `audio cleanup --confirm` running concurrently
- When: the cleanup scans rows for deletion
- Then: no file is deleted that the recording row still references from a previous or pending state

#### Scenario: Failed save leaves no partial file and rolls back the row
- Given: a save that fails during the copy or finalize step (e.g. disk full)
- When: the failure is handled
- Then: no partial file exists at the final path, the row's `file_path` is rolled back to its previous value (or empty), and any staged temporary file is removed

---

### Requirement: Kept WAV recordings persist to storage without temp leaks
The system **SHALL**, when `keep_wav` is enabled, persist the recorded WAV into the configured recordings storage as the recording's canonical file with `format='wav'`, keep the MP3 transient for upload only, and **MUST** remove both the temporary WAV and the temporary MP3 afterwards — in success and failure — so no audio file leaks into the system temp directory.

#### Scenario: keep_wav enabled persists the WAV
- Given: `keep_wav=True` and a successful dictation
- When: the dictation flow finishes
- Then: a WAV file exists under the recordings root, the row's `file_path` points at it with `format='wav'`, and no temporary WAV or MP3 remains in the temp directory

#### Scenario: keep_wav disabled converts and cleans up
- Given: `keep_wav=False` and a successful dictation
- When: the dictation flow finishes
- Then: only the MP3 is persisted, the temporary WAV is removed during conversion, and no temporary audio files remain

#### Scenario: Failed dictation with keep_wav leaves no temp files
- Given: `keep_wav=True` and a dictation whose transcription fails
- When: the failure cleanup runs
- Then: the temporary WAV and MP3 are both removed and no audio file remains in the temp directory

---

### Requirement: Regression tests cover storage path safety and persistence
The system **SHALL** include automated regression tests covering path containment (absolute, `..`, legacy in-root absolute paths, empty sentinel), atomic claim-first saves, and `keep_wav` persistence with temp-file cleanup.

#### Scenario: Storage regression test suite runs
- Given: a test suite exercising `get_audio_path()` with absolute, traversing, legacy-in-root, and empty paths, plus `save_audio` success/failure and `keep_wav` flows
- When: the test suite is executed
- Then: escaping paths are rejected without file access, empty paths behave as "no file", saves are atomic and claim-first, and no temp files remain after `keep_wav` flows
