# Audio Storage Specification

## Purpose

This specification defines the audio file storage capability of the whisper-dictate system: the recordings directory layout (including date-based subdirectories), saving audio recordings to the filesystem with unique filenames, retrieving recording file paths, and cleaning up audio files (single recordings and orphaned files).

## Requirements

### Requirement: Audio file storage directory
The system SHALL create and manage the audio storage directory structure.

#### Scenario: Create recordings directory on first use
- **WHEN** the application starts and the recordings directory does not exist
- **THEN** the system creates the directory at `~/.local/share/whisper-dictate/recordings/`

#### Scenario: Create date-based subdirectories
- **WHEN** a recording is saved
- **THEN** the system creates year/month/day subdirectories (e.g., `2024/03/15/`) if they do not exist

---

### Requirement: Save audio recording to filesystem
The system SHALL save audio recordings to the filesystem instead of deleting them.

#### Scenario: Save recording after transcription
- **WHEN** transcription completes successfully
- **THEN** the system moves or copies the audio file from temporary storage to the persistent recordings directory

#### Scenario: Generate unique filename for recording
- **WHEN** saving a new recording
- **THEN** the system generates a unique filename using timestamp and random suffix to avoid collisions

#### Scenario: Handle save failure
- **WHEN** saving a recording fails due to disk space or permission issues
- **THEN** the system logs an error, continues with transcription, and marks the recording as "not saved" in the database

---

### Requirement: Audio file retrieval
The system SHALL provide access to saved audio recordings.

#### Scenario: Get recording file path by ID
- **WHEN** a request is made to get the audio file path for a recording ID
- **THEN** the system returns the absolute path to the audio file if it exists

#### Scenario: Verify recording file exists
- **WHEN** accessing a recording's audio file
- **THEN** the system verifies the file exists on the filesystem and returns an error if missing

---

### Requirement: Audio file cleanup
The system SHALL provide a mechanism to clean up old audio recordings.

#### Scenario: Delete recording audio file
- **WHEN** a recording is deleted from the database
- **THEN** the system also deletes the corresponding audio file from the filesystem

#### Scenario: Cleanup orphaned files
- **WHEN** a cleanup operation is triggered
- **THEN** the system scans the recordings directory and removes any audio files not referenced in the database
