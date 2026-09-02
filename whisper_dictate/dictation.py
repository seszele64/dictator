"""Main dictation service orchestrating audio recording and transcription."""

import logging
from pathlib import Path
from types import TracebackType
from typing import Any

import soundfile as sf

from whisper_dictate.audio import AudioRecorder
from whisper_dictate.audio_converter import AudioConverter
from whisper_dictate.audio_storage import AudioStorage, StagedAudio
from whisper_dictate.clipboard import ClipboardManager
from whisper_dictate.config import AppConfig
from whisper_dictate.database import Database
from whisper_dictate.transcription import (
    TranscriptionResult,
    create_transcriber,
)

logger = logging.getLogger(__name__)


class DictationService:
    """WHY THIS EXISTS: Dictation workflow needs to be orchestrated to provide
    a seamless user experience from recording to clipboard.

    RESPONSIBILITY: Coordinate audio recording, transcription, and clipboard operations.
    BOUNDARIES:
    - DOES: Manage the complete dictation workflow
    - DOES NOT: Handle user interface or command-line parsing

    RELATIONSHIPS:
    - DEPENDS ON: AudioRecorder, TranscriptionProvider, ClipboardManager, Database, AudioStorage
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

        # Initialize audio storage (per instance; database is lazy below)
        self._db: Database | None = None
        self._storage: AudioStorage | None = None

    @property
    def database(self) -> Database:
        """Get or create database instance (lazy initialization).

        Returns:
            Database: Initialized database instance
        """
        if self._db is None:
            # Construct a dedicated database for this service instance from
            # the user-configured settings, never module-level defaults
            self._db = Database(self.config.database)
            # Initialize database connection
            self._db.initialize()
        return self._db

    @property
    def audio_storage(self) -> AudioStorage:
        """Get or create audio storage instance (lazy initialization).

        Returns:
            AudioStorage: Initialized audio storage instance
        """
        if self._storage is None:
            self._storage = AudioStorage(self.config.database)
        return self._storage

    def check_disk_space(self) -> tuple[bool, int]:
        """Check if there's enough disk space for recording.

        Returns:
            Tuple[bool, int]: (has_space, available_mb) - True if enough space available,
                             and the available space in MB
        """
        min_free_mb = self.config.database.min_free_space_mb
        return self.audio_storage.check_disk_space(min_free_mb)

    def _save_audio_claim_first(
        self,
        recording_id: int | None,
        source_file: Path,
        audio_format: str,
    ) -> Path:
        """Persist the audio file with claim-first ordering.

        Stages the file, claims the row's ``file_path`` in the database, then
        atomically finalizes with ``os.replace()``. This closes the window
        where ``audio cleanup --confirm`` could delete a just-saved file whose
        row still references the old (empty) path. On finalize failure the
        claim is rolled back and the staging file is removed.

        Args:
            recording_id: Recording row ID (claim skipped when None)
            source_file: Audio file to persist
            audio_format: Audio format suffix (wav/mp3)

        Returns:
            Path: Final path of the persisted file
        """
        staged: StagedAudio = self.audio_storage.stage_audio(
            source_file, suffix=audio_format
        )

        # Claim the final path before finalizing so cleanup can never race us
        if recording_id is not None:
            self.database.update_recording_file_path(
                recording_id, str(staged.relative_path)
            )

        try:
            return self.audio_storage.finalize_audio(staged)
        except Exception:
            # Roll back the claim: the row must not point at a path that was
            # never written.
            if recording_id is not None:
                try:
                    self.database.update_recording_file_path(recording_id, "")
                except Exception as rollback_error:
                    logger.warning(
                        f"Failed to roll back file_path claim: {rollback_error}"
                    )
            raise

    def dictate(
        self, duration: float | None = None
    ) -> TranscriptionResult | None:
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
        wav_file: Path | None = None
        converted_file: Path | None = None
        recording_id: int | None = None
        recording_saved = False

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

            # Track every temp file created by the flow for cleanup in finally
            converted_file = audio_file if audio_file != wav_file else None

            # With keep_wav=True the WAV is the canonical persisted file and the
            # MP3 stays transient (used only for the API upload); otherwise the
            # converted file itself is persisted.
            if self.config.audio.keep_wav and converted_file is not None:
                persist_file = wav_file
                persist_format = "wav"
            else:
                persist_file = audio_file
                persist_format = audio_format

            # Create recording entry in database (status: recording)
            try:
                recording_id = self.database.create_recording(
                    file_path="",  # Claimed after the audio is staged
                    duration=actual_duration,
                    format=persist_format,
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

            # Save audio to persistent storage and update recording (claim-first)
            try:
                saved_path = self._save_audio_claim_first(
                    recording_id, persist_file, persist_format
                )
                recording_saved = True
                logger.info(f"Audio saved to persistent storage: {saved_path}")
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

        except BaseException as e:
            # BaseException (not just Exception) so interrupted dictation
            # (KeyboardInterrupt/Ctrl+C) also cleans up before propagating.
            failure_label = str(e) or type(e).__name__
            logger.error(f"Dictation workflow failed: {failure_label}")

            # Remove the in-progress row so failed/interrupted dictations do
            # not leave orphaned rows in history.
            self._cleanup_failed_recording(recording_id, recording_saved)

            # Log error to database
            try:
                if recording_id is not None:
                    self.database.create_log(
                        level="ERROR",
                        message=f"Dictation failed: {failure_label}",
                        source="dictation",
                        metadata={"recording_id": recording_id},
                    )
            except Exception:
                pass  # Don't fail if logging fails

            raise
        finally:
            # Unlink every temporary file the flow created (the WAV and the
            # transient MP3) regardless of success/failure, so /tmp never
            # leaks audio files. Files already consumed (e.g. deleted by the
            # converter) simply do not exist anymore.
            for temp_file in (wav_file, converted_file):
                if temp_file is None:
                    continue
                try:
                    if temp_file.exists():
                        temp_file.unlink()
                        logger.debug(f"Cleaned up temporary file: {temp_file}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary file: {e}")

    def transcribe_existing(
        self,
        recording_id: int | None,
        audio_file: Path,
        audio_format: str = "wav",
        copy_to_clipboard: bool | None = None,
    ) -> TranscriptionResult:
        """Transcribe an already-recorded audio file (toggle flow).

        WHY THIS EXISTS: the toggle duplicated the dictation persistence
        logic (claim-first audio save, duration update, transcript rows)
        with its own recording stack and raw SQL. This method is the shared
        seam: the toggle keeps only its arecord/PID/state orchestration and
        user notifications and hands the recorded file here.

        Parity contract with the former ``toggle.transcribe_audio``:
        - Claim-first save via ``_save_audio_claim_first`` (stage → claim
          the row's ``file_path`` → finalize; a finalize failure rolls the
          claim back to the empty-string sentinel).
        - A save failure is warn-and-continue: the original ``audio_file``
          is transcribed instead, the transcript is still stored, and the
          text is still copied.
        - Duration is always computed from the file that was actually
          transcribed via ``soundfile.info`` and written with
          ``update_recording_duration`` (best effort).
        - Silence → empty transcript row + early return: no clipboard copy
          and no log row.
        - Non-silence → transcript row (confidence read via ``getattr`` —
          not every provider response includes it) + clipboard copy unless
          ``copy_to_clipboard`` is False (``None`` defers to
          ``config.copy_to_clipboard``).
        - No ``create_log()`` rows are ever written: the toggle flow logs
          to the file logger, not the database.
        - Any failure removes the in-progress recording row (kept when the
          audio persisted or a transcript was stored) and re-raises.

        Args:
            recording_id: Recording row to claim and persist against
                (persistence is skipped when None)
            audio_file: Recorded audio file to transcribe and persist
            audio_format: Audio format suffix (the toggle records WAV)
            copy_to_clipboard: Force the clipboard copy on/off; None defers
                to the configuration

        Returns:
            TranscriptionResult: The transcription result (check
            ``silence_detected`` for the silence outcome)

        Raises:
            Exception: Re-raises any exceptions from underlying services
        """
        audio_saved = False
        transcript_stored = False
        try:
            # Claim-first save: claim the row's file_path before finalizing
            # so audio cleanup can never delete a just-saved file whose row
            # still points elsewhere.
            saved_path: Path | None = None
            try:
                saved_path = self._save_audio_claim_first(
                    recording_id, audio_file, audio_format
                )
                audio_saved = True
                logger.info(f"Audio saved to persistent storage: {saved_path}")
            except Exception as e:
                logger.warning(f"Failed to save audio to persistent storage: {e}")
                # The claim rollback (row back to the "" sentinel) is handled
                # inside _save_audio_claim_first; transcribe the source file.

            audio_to_transcribe = saved_path if saved_path else audio_file

            # Calculate and update the recording duration from the audio
            # that was actually transcribed
            if recording_id:
                try:
                    audio_info = sf.info(audio_to_transcribe)
                    duration = audio_info.duration
                    self.database.update_recording_duration(recording_id, duration)
                    logger.debug(
                        f"Updated recording {recording_id} with duration: {duration:.2f}s"
                    )
                except Exception as e:
                    logger.warning(f"Failed to calculate recording duration: {e}")

            result = self.transcriber.transcribe_audio(audio_to_transcribe)

            # Handle silence detection - skip clipboard, DB transcript text,
            # and log; only the empty transcript row is written
            if result.silence_detected:
                logger.info(
                    "Silence detected - skipping clipboard copy and transcript storage"
                )

                if recording_id:
                    try:
                        self.database.create_transcript(
                            recording_id=recording_id,
                            text="",
                            language=result.language,
                            model_used=self.config.openai.model,
                            confidence=None,
                        )
                        transcript_stored = True
                    except Exception as e:
                        logger.warning(f"Failed to create empty transcript entry: {e}")

                return result  # Early return: no clipboard copy

            # Store transcript in database
            if recording_id:
                try:
                    confidence = getattr(result, "confidence", None)
                    self.database.create_transcript(
                        recording_id=recording_id,
                        text=result.text,
                        language=result.language,
                        model_used=self.config.openai.model,
                        confidence=confidence,
                    )
                    transcript_stored = True
                    logger.debug(
                        f"Created transcript entry for recording {recording_id}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to create transcript entry: {e}")

            # Copy to clipboard if enabled (never for silence)
            should_copy = (
                self.config.copy_to_clipboard
                if copy_to_clipboard is None
                else copy_to_clipboard
            )
            if should_copy:
                success = self.clipboard.copy_to_clipboard(result.text)
                if success:
                    logger.info("Transcription copied to clipboard")
                else:
                    logger.warning("Failed to copy to clipboard")

            logger.info(f"Transcription completed: {result.text}")
            return result

        except BaseException as e:
            # BaseException (not just Exception) so an interrupted
            # transcription also cleans up before propagating.
            failure_label = str(e) or type(e).__name__
            logger.error(f"Transcription workflow failed: {failure_label}")

            # Remove the in-progress row so failed/interrupted transcriptions
            # do not leave orphaned rows in history. The row is kept when the
            # audio persisted OR a transcript was stored - deleting those
            # would orphan real data.
            self._cleanup_failed_recording(
                recording_id, audio_saved or transcript_stored
            )

            raise

    def _cleanup_failed_recording(
        self, recording_id: int | None, recording_saved: bool
    ) -> None:
        """Delete the in-progress recording row after a failure or interruption.

        Rows that already received their persisted audio are kept - deleting
        those would orphan the file on disk. Callers may also pass True when
        a transcript row was stored (e.g. the toggle delegation flow), for
        the same reason: the row is no longer "in progress".

        Args:
            recording_id: Recording row ID (None if never created)
            recording_saved: True once the audio file was persisted and
                claimed (or the row is otherwise no longer in-progress)
        """
        if recording_id is None or recording_saved:
            return
        try:
            if self.database.delete_recording(recording_id):
                logger.info(
                    f"Removed in-progress recording entry {recording_id} after failure"
                )
        except Exception as e:
            logger.warning(f"Failed to clean up in-progress recording entry: {e}")

    def close(self) -> None:
        """Close the database connection."""
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
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context manager with proper cleanup.

        Args:
            exc_type: Exception type if an exception was raised
            exc_val: Exception value if an exception was raised
            exc_tb: Exception traceback if an exception was raised

        Returns:
            None: Exceptions are not suppressed
        """
        self.close()

    def get_system_info(self) -> dict[str, Any]:
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
