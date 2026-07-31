"""Main dictation service orchestrating audio recording and transcription."""

import logging
from pathlib import Path
from types import TracebackType
from typing import Optional, Tuple

from whisper_dictate.config import AppConfig, DatabaseConfig
from whisper_dictate.audio import AudioRecorder
from whisper_dictate.transcription import (
    create_transcriber,
    TranscriptionResult,
)
from whisper_dictate.clipboard import ClipboardManager
from whisper_dictate.database import Database, get_database
from whisper_dictate.audio_storage import AudioStorage, get_audio_storage
from whisper_dictate.audio_converter import AudioConverter

logger = logging.getLogger(__name__)


class DictationService:
    """WHY THIS EXISTS: Dictation workflow needs to be orchestrated to provide
    a seamless user experience from recording to clipboard.

    RESPONSIBILITY: Coordinate audio recording, transcription, and clipboard operations.
    BOUNDARIES:
    - DOES: Manage the complete dictation workflow
    - DOES NOT: Handle user interface or command-line parsing

    RELATIONSHIPS:
    - DEPENDS ON: AudioRecorder, WhisperTranscriber, ClipboardManager, Database, AudioStorage
    - USED BY: CLI interface for dictation operations
    """

    def __init__(self, config: AppConfig) -> None:
        """Initialize dictation service with configuration.

        Args:
            config: Application configuration
        """
        self.config = config
        self.audio_recorder = AudioRecorder(config.audio)
        self.transcriber = create_transcriber(config.openai)
        self.clipboard = ClipboardManager()

        # Initialize audio converter for MP3 support
        self.audio_converter = AudioConverter(
            bitrate=config.audio.mp3_bitrate, keep_wav=config.audio.keep_wav
        )

        # Initialize database and audio storage
        self._db: Optional[Database] = None
        self._audio_storage: Optional[AudioStorage] = None

    @property
    def database(self) -> Database:
        """Get or create database instance (lazy initialization).

        Returns:
            Database: Initialized database instance
        """
        if self._db is None:
            db_config = DatabaseConfig()
            self._db = get_database(db_config)
            # Initialize database connection
            self._db.initialize()
        return self._db

    @property
    def audio_storage(self) -> AudioStorage:
        """Get or create audio storage instance (lazy initialization).

        Returns:
            AudioStorage: Initialized audio storage instance
        """
        if self._audio_storage is None:
            db_config = DatabaseConfig()
            self._audio_storage = get_audio_storage(db_config)
        return self._audio_storage

    def check_disk_space(self) -> Tuple[bool, int]:
        """Check if there's enough disk space for recording.

        Returns:
            Tuple[bool, int]: (has_space, available_mb) - True if enough space available,
                             and the available space in MB
        """
        db_config = DatabaseConfig()
        min_free_mb = db_config.min_free_space_mb
        return self.audio_storage.check_disk_space(min_free_mb)

    def dictate(
        self, duration: Optional[float] = None
    ) -> Optional[TranscriptionResult]:
        """WHY THIS EXISTS: Users need a single method to perform complete
        dictation workflow without managing individual components.

        RESPONSIBILITY: Execute complete dictation workflow with persistence.
        BOUNDARIES:
        - DOES: Record, transcribe, save to persistent storage, and optionally copy to clipboard
        - DOES NOT: Handle user interaction or error display

        Args:
            duration: Recording duration in seconds (uses config default if None)

        Returns:
            Optional[TranscriptionResult]: Transcription result if successful, None if failed

        Raises:
            Exception: Re-raises any exceptions from underlying services
        """
        audio_file: Optional[Path] = None
        recording_id: Optional[int] = None

        try:
            # Check disk space before recording
            has_space, available_mb = self.check_disk_space()
            if not has_space:
                logger.warning(
                    f"Low disk space: only {available_mb}MB available. "
                    f"Recording may fail if disk fills up."
                )

            # Record audio
            logger.info("Starting dictation workflow")
            wav_file = self.audio_recorder.record_to_file(duration)

            # Determine recording duration
            actual_duration = duration or self.config.audio.duration

            # Convert to MP3 if enabled (before transcription)
            # The audio_file may be WAV or MP3 depending on mp3_enabled setting
            audio_file = wav_file
            audio_format = "wav"
            if self.config.audio.mp3_enabled:
                logger.info(
                    f"Converting WAV to MP3 (bitrate={self.config.audio.mp3_bitrate})"
                )
                audio_file = self.audio_converter.convert(
                    wav_file, delete_source=not self.config.audio.keep_wav
                )
                if audio_file.suffix == ".mp3":
                    audio_format = "mp3"
                    logger.info(f"Using MP3 for transcription: {audio_file}")
                else:
                    # Conversion failed, fell back to WAV
                    logger.warning("MP3 conversion failed, using WAV for transcription")
                    audio_format = "wav"

            # Create recording entry in database (status: recording)
            try:
                recording_id = self.database.create_recording(
                    file_path="",  # Will be updated after saving
                    duration=actual_duration,
                    format=audio_format,
                    sample_rate=self.config.audio.sample_rate,
                    channels=self.config.audio.channels,
                )
                logger.debug(f"Created recording entry with ID: {recording_id}")
            except Exception as e:
                logger.warning(f"Failed to create recording entry: {e}")
                recording_id = None

            # Transcribe audio (may be WAV or MP3)
            result = self.transcriber.transcribe_audio(audio_file)

            # Handle silence detection - skip clipboard, DB transcript, and log
            if result.silence_detected:
                logger.info("Silence detected - skipping clipboard copy and transcript storage")
                
                # Still store recording but with empty transcript
                if recording_id is not None:
                    try:
                        self.database.create_transcript(
                            recording_id=recording_id,
                            text="",
                            language=result.language,
                            model_used=self.config.openai.model,
                            confidence=None,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to create empty transcript entry: {e}")
                
                # Log silence detection
                try:
                    self.database.create_log(
                        level="INFO",
                        message="Silence detected, transcription skipped",
                        source="dictation",
                        metadata={
                            "recording_id": recording_id,
                            "duration": actual_duration,
                        },
                    )
                except Exception as e:
                    logger.debug(f"Failed to log silence detection: {e}")
                
                return result  # Return early, skip clipboard copy

            # Save audio to persistent storage and update recording
            try:
                # Move audio to persistent storage
                saved_path, relative_path = self.audio_storage.save_audio(audio_file)
                logger.info(f"Audio saved to persistent storage: {saved_path}")

                # Update recording entry with actual file path
                if recording_id is not None:
                    self.database.execute(
                        "UPDATE recordings SET file_path = ? WHERE id = ?",
                        (relative_path, recording_id),
                    )
            except Exception as e:
                logger.warning(f"Failed to save audio to persistent storage: {e}")
                # Continue even if storage fails - transcription still valuable

            # Store transcript in database
            if recording_id is not None:
                try:
                    # Get confidence if available (not all Whisper responses include it)
                    confidence = getattr(result, "confidence", None)
                    self.database.create_transcript(
                        recording_id=recording_id,
                        text=result.text,
                        language=result.language,
                        model_used=self.config.openai.model,
                        confidence=confidence,
                    )
                    logger.debug(
                        f"Created transcript entry for recording {recording_id}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to create transcript entry: {e}")

            # Log transcription event
            try:
                self.database.create_log(
                    level="INFO",
                    message="Transcription completed",
                    source="dictation",
                    metadata={
                        "recording_id": recording_id,
                        "duration": actual_duration,
                        "language": result.language,
                    },
                )
            except Exception as e:
                logger.debug(f"Failed to log transcription event: {e}")

            # Copy to clipboard if enabled (only if not silence-detected)
            if self.config.copy_to_clipboard and not result.silence_detected:
                success = self.clipboard.copy_to_clipboard(result.text)
                if success:
                    logger.info("Transcription copied to clipboard")
                else:
                    logger.warning("Failed to copy to clipboard")

            logger.info("Dictation workflow completed successfully")
            return result

        except Exception as e:
            logger.error(f"Dictation workflow failed: {e}")

            # Log error to database
            try:
                if recording_id is not None:
                    self.database.create_log(
                        level="ERROR",
                        message=f"Dictation failed: {e}",
                        source="dictation",
                        metadata={"recording_id": recording_id},
                    )
            except Exception:
                pass  # Don't fail if logging fails

            raise
        finally:
            # Clean up temporary audio file (only if not saved to persistent storage)
            if audio_file and audio_file.exists():
                try:
                    # Only delete if it's still in temp location
                    audio_file.unlink()
                    logger.debug(f"Cleaned up temporary file: {audio_file}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary file: {e}")

    def close(self) -> None:
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None

    def close_sync(self) -> None:
        """Synchronous wrapper for close()."""
        if self._db:
            self._db.close()
            self._db = None

    def __enter__(self) -> "DictationService":
        """Enter context manager.

        Returns:
            DictationService: Self for use in with statement
        """
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit context manager with proper cleanup.

        Args:
            exc_type: Exception type if an exception was raised
            exc_val: Exception value if an exception was raised
            exc_tb: Exception traceback if an exception was raised

        Returns:
            None: Exceptions are not suppressed
        """
        self.close_sync()

    def get_system_info(self) -> dict:
        """WHY THIS EXISTS: Users need diagnostic information to troubleshoot
        configuration issues.

        RESPONSIBILITY: Provide system diagnostic information.
        BOUNDARIES:
        - DOES: Gather system information for diagnostics
        - DOES NOT: Perform system modifications

        Returns:
            dict: System diagnostic information
        """
        return {
            "audio_devices": self.audio_recorder.get_audio_devices(),
            "clipboard_tools": self.clipboard.available_tools,
            "config": {
                "audio_sample_rate": self.config.audio.sample_rate,
                "audio_channels": self.config.audio.channels,
                "audio_duration": self.config.audio.duration,
                "copy_to_clipboard": self.config.copy_to_clipboard,
                "openai_model": self.config.openai.model,
            },
            "persistence": {
                "database_path": str(self.database.path),
                "recordings_path": str(self.audio_storage.recordings_path),
            },
        }
