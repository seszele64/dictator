# MP3 Audio Conversion Specification

## Purpose

This specification defines the MP3 audio conversion capability for the dictator system. The system SHALL provide the ability to convert WAV audio recordings to MP3 format to achieve significant file size reduction while preserving audio quality suitable for speech recognition via the Whisper API.

The MP3 audio conversion capability enables:
- Automatic conversion of WAV recordings to MP3 format after capture
- Configurable bitrate settings for quality/size tradeoff
- Optional preservation of original WAV files
- Seamless integration with the Whisper transcription pipeline
- Format tracking in the recording database

## Requirements

### Requirement: AudioConverter converts WAV files to MP3 format

The system SHALL provide an AudioConverter class that converts WAV audio files to MP3 format using pydub with FFmpeg backend.

#### Scenario: Successful WAV to MP3 conversion

- **WHEN** AudioConverter.convert() is called with a valid WAV file path
- **THEN** the system SHALL create an MP3 file at the same location with .mp3 extension
- **AND** the MP3 file SHALL use the configured bitrate (default 128 kbps)

#### Scenario: MP3 conversion with custom bitrate

- **WHEN** AudioConverter is initialized with bitrate="64k"
- **AND** convert() is called on a WAV file
- **THEN** the resulting MP3 file SHALL be encoded at 64 kbps

#### Scenario: Conversion failure falls back to original WAV

- **WHEN** AudioConverter.convert() is called but FFmpeg is not available
- **THEN** the system SHALL log a warning and return the original WAV path
- **AND** the system SHALL continue without error

#### Scenario: Source file deletion after successful conversion

- **WHEN** convert() is called with delete_source=True
- **AND** the conversion completes successfully
- **THEN** the original WAV file SHALL be deleted after the MP3 is created

---

### Requirement: AudioConverter preserves WAV files when configured

The system SHALL preserve original WAV files when keep_wav configuration is enabled.

#### Scenario: WAV file preserved when keep_wav is True

- **WHEN** keep_wav is set to True in configuration
- **AND** AudioConverter.convert() is called on a WAV file
- **THEN** the original WAV file SHALL be retained alongside the new MP3 file

#### Scenario: WAV file deleted when keep_wav is False

- **WHEN** keep_wav is set to False in configuration
- **AND** AudioConverter.convert() is called on a WAV file
- **THEN** the original WAV file SHALL be deleted after successful MP3 creation

---

### Requirement: AudioConfig includes MP3 conversion settings

The system SHALL provide configuration options for MP3 conversion in AudioConfig.

#### Scenario: Default MP3 configuration values

- **WHEN** AudioConfig is initialized with no arguments
- **THEN** mp3_enabled SHALL default to True
- **AND** mp3_bitrate SHALL default to "128k"
- **AND** keep_wav SHALL default to False

#### Scenario: Custom MP3 configuration

- **WHEN** AudioConfig is initialized with mp3_bitrate="64k" and keep_wav=True
- **THEN** the configuration SHALL reflect those exact values

#### Scenario: MP3 can be disabled entirely

- **WHEN** mp3_enabled is set to False
- **THEN** audio files SHALL be kept in their original format (WAV)

---

### Requirement: WhisperTranscriber accepts MP3 files for transcription

The system SHALL support MP3 files as input for Whisper API transcription.

#### Scenario: MP3 file transcription

- **WHEN** WhisperTranscriber.transcribe_audio() receives a Path with .mp3 extension
- **THEN** the system SHALL send the MP3 file directly to the Whisper API
- **AND** the transcription result SHALL be returned normally

#### Scenario: Whisper API natively supports MP3

- **WHEN** an MP3 file is sent to the Whisper API
- **THEN** the API SHALL process it without format conversion requirements

---

### Requirement: File size reduction with MP3 encoding

The system SHALL achieve significant file size reduction when converting to MP3.

#### Scenario: MP3 at 128 kbps achieves 80-90% size reduction

- **WHEN** a 10MB WAV file is converted to MP3 at 128 kbps
- **THEN** the resulting MP3 file SHALL be between 1-2 MB

#### Scenario: Lower bitrate for speech produces identical transcription

- **WHEN** a WAV file is converted to MP3 at 32-64 kbps
- **AND** the resulting MP3 is transcribed
- **THEN** the transcription text SHALL be identical to the WAV transcription

---

### Requirement: Recording format metadata

The system SHALL track the audio format of each recording in the database.

#### Scenario: Store format for new recordings

- **WHEN** a new recording is created with MP3 format
- **THEN** the format column SHALL be set to 'mp3'
- **AND** the format column SHALL be stored in the recordings table

#### Scenario: Store format for WAV recordings

- **WHEN** a new recording is created with WAV format (MP3 disabled)
- **THEN** the format column SHALL be set to 'wav'
