#!/usr/bin/env python3
"""
Fixed toggle dictation for i3 - proper real-time recording with immediate start/stop.
With database integration for persistence and state management.
"""

import logging
import os
import signal
import subprocess
import sys
import time

import soundfile as sf

from whisper_dictate.audio_storage import get_audio_storage
from whisper_dictate.clipboard import ClipboardManager
from whisper_dictate.config import AppPaths, load_config
from whisper_dictate.database import get_database
from whisper_dictate.dunst_monitor import ensure_dunst_running
from whisper_dictate.notifications import (
    notify_error,
    notify_recording_start,
    notify_recording_stop,
    notify_recording_stopped,
    notify_stopping_transcription,
)
from whisper_dictate.transcription import create_transcriber

# State and process tracking
# Note: Using database for state management (preferred), with file fallbacks for compatibility
# These are the SAME legacy dotfiles migration.py treats as its migration
# sources — both modules resolve them through AppPaths so the toggle's
# runtime paths and the migration's source paths can never drift apart.
_paths = AppPaths()
STATE_FILE = _paths.legacy_state_file
PID_FILE = _paths.legacy_pid_file
AUDIO_FILE = _paths.legacy_audio_file

# Database state keys
STATE_KEY_RECORDING = "is_recording"
STATE_KEY_RECORDING_ID = "current_recording_id"


def setup_logging():
    """WHY THIS EXISTS: Logging needs to be configured consistently
    across the application for debugging and monitoring.

    RESPONSIBILITY: Configure logging with file output to whisper-dictate.log.
    BOUNDARIES:
    - DOES: Set up logging configuration with file output
    - DOES NOT: Handle log rotation or file management
    """
    # Log directory from the single source of truth (XDG state home)
    paths = AppPaths()
    paths.log_dir.mkdir(parents=True, exist_ok=True)

    log_file = paths.log_file

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def get_db_and_storage(config=None):
    """Get database and audio storage instances.

    Args:
        config: Loaded application configuration. When None, configuration is
            loaded so the user's configured database paths are always honored.

    Returns:
        tuple: (database, audio_storage)
    """
    if config is None:
        # Module-level load_config (kept patchable for tests that redirect
        # storage paths); honors the user's configured database paths.
        config = load_config()
    db_config = config.database
    db = get_database(db_config)
    db.initialize()
    audio_storage = get_audio_storage(db_config)
    return db, audio_storage


def is_recording(config=None):
    """Check if currently recording.

    Checks database state first, falls back to file-based state for compatibility.

    Args:
        config: Loaded application configuration (loaded when None)

    Returns:
        bool: True if recording, False otherwise.
    """
    db = None
    try:
        db, _ = get_db_and_storage(config)
        is_recording = db.get_state(STATE_KEY_RECORDING)
        if is_recording is True:
            return True
        logging.debug("Database reports not recording, checking file-based state")
    except Exception as e:
        logging.warning(f"Failed to check database state, falling back to files: {e}")
    finally:
        if db is not None:
            db.close()

    # Fallback to file-based state (legacy compatibility)
    file_state = PID_FILE.exists() and STATE_FILE.exists()
    if file_state:
        logging.info("Recording detected via file-based fallback")
    return file_state


def get_recording_pid():
    """Get the PID of the recording process."""
    try:
        if PID_FILE.exists():
            return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        pass
    return None


def start_background_recording(config):
    """Start background recording process using arecord."""
    db = None
    try:
        # Build the command - use default device
        cmd = [
            "arecord",
            "-f",
            "cd",  # CD quality: 16-bit little-endian, 44100Hz, stereo
            "-t",
            "wav",
            str(AUDIO_FILE),
        ]

        # Start the recording process
        process = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Save PID for later management
        PID_FILE.write_text(str(process.pid))
        STATE_FILE.touch()

        # Create recording entry in database
        recording_id = None
        try:
            db, _ = get_db_and_storage(config)
            # Create initial recording entry. An empty file_path is the
            # "no file yet" sentinel: the absolute temp path would escape the
            # recordings root, and the real path is claimed after the save.
            recording_id = db.create_recording(
                file_path="",
                duration=None,  # Will be updated on stop
                format="wav",  # toggle_dictate.py always records WAV
                sample_rate=44100,
                channels=2,
            )
            # Set state in database
            db.set_state(STATE_KEY_RECORDING, True)
            db.set_state(STATE_KEY_RECORDING_ID, recording_id)
            logging.debug(f"Created database recording entry with ID: {recording_id}")
        except Exception as e:
            logging.warning(f"Failed to create database recording entry: {e}")

        logging.info("Recording started")
        notify_recording_start()

        return process

    except Exception as e:
        logging.error(f"Failed to start recording: {e}")
        notify_error(f"Failed to start recording: {e}")
        return None

    finally:
        # Always close database connection
        if db is not None:
            db.close()


def stop_background_recording(config=None):
    """Stop background recording and process the audio.

    Returns:
        tuple: (success: bool, recording_id: int or None) - Returns the recording_id
               before clearing it from state, so it can be used for transcription.
    """
    recording_id = None
    db = None

    try:
        # Get recording_id BEFORE clearing state (for transcription use)
        try:
            db, _ = get_db_and_storage(config)
            recording_id = db.get_state(STATE_KEY_RECORDING_ID)
        except Exception as e:
            logging.debug(f"Failed to get recording_id: {e}")

        pid = get_recording_pid()
        if pid:
            # Kill the recording process
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)  # Give it time to stop
                os.kill(pid, signal.SIGKILL)  # Force kill if needed
            except ProcessLookupError:
                pass  # Process already dead

            # Clean up PID file
            if PID_FILE.exists():
                PID_FILE.unlink()

        # Clean up state file
        if STATE_FILE.exists():
            STATE_FILE.unlink()

        # Clear database state (reuse db connection if available)
        try:
            if db is None:
                db, _ = get_db_and_storage(config)
            db.set_state(STATE_KEY_RECORDING, False)
            db.delete_state(STATE_KEY_RECORDING_ID)
        except Exception as e:
            logging.debug(f"Failed to clear database state: {e}")

        return True, recording_id

    except Exception as e:
        logging.error(f"Error stopping recording: {e}")
        return False, None

    finally:
        # Always close database connection
        if db is not None:
            db.close()


def transcribe_audio(config, recording_id=None):
    """Transcribe the recorded audio.

    Args:
        config: Configuration object
        recording_id: Optional recording ID. If not provided, will attempt to get from state.
    """
    db = None
    audio_saved = False
    transcript_stored = False
    try:
        if not AUDIO_FILE.exists():
            logging.error("No audio file found")
            return None

        logging.info("Starting transcription")

        # Get database and audio storage
        db, audio_storage = get_db_and_storage(config)

        # Get recording ID from parameter or fall back to state lookup
        if recording_id is None:
            recording_id = db.get_state(STATE_KEY_RECORDING_ID)

        # Save audio to persistent storage with claim-first ordering: claim
        # the row's file_path before finalizing so audio cleanup can never
        # delete a just-saved file whose row still points elsewhere.
        saved_path = None
        try:
            staged = audio_storage.stage_audio(AUDIO_FILE)
            if recording_id:
                db.execute(
                    "UPDATE recordings SET file_path = ? WHERE id = ?",
                    (staged.relative_path, recording_id),
                )
            saved_path = audio_storage.finalize_audio(staged)
            audio_saved = True
            logging.info(f"Audio saved to persistent storage: {saved_path}")
        except Exception as e:
            logging.warning(f"Failed to save audio to persistent storage: {e}")
            # Roll back the claim so the row does not point at an unwritten path
            if recording_id:
                try:
                    db.execute(
                        "UPDATE recordings SET file_path = '' WHERE id = ?",
                        (recording_id,),
                    )
                except Exception as rollback_error:
                    logging.warning(
                        f"Failed to roll back file_path claim: {rollback_error}"
                    )

        # Transcribe audio
        transcriber = create_transcriber(config.openai)
        audio_to_transcribe = saved_path if saved_path else AUDIO_FILE

        # Calculate and update recording duration
        if recording_id:
            try:
                audio_info = sf.info(audio_to_transcribe)
                duration = audio_info.duration
                db.execute(
                    "UPDATE recordings SET duration = ? WHERE id = ?",
                    (duration, recording_id),
                )
                logging.debug(
                    f"Updated recording {recording_id} with duration: {duration:.2f}s"
                )
            except Exception as e:
                logging.warning(f"Failed to calculate recording duration: {e}")

        result = transcriber.transcribe_audio(audio_to_transcribe)

        # Handle silence detection
        if result.silence_detected:
            logging.info("Silence detected - skipping clipboard copy and transcript storage")

            # Create empty transcript entry
            if recording_id:
                try:
                    db.create_transcript(
                        recording_id=recording_id,
                        text="",
                        language=result.language,
                        model_used=config.openai.model,
                        confidence=None,
                    )
                    transcript_stored = True
                except Exception as e:
                    logging.warning(f"Failed to create empty transcript entry: {e}")

            # Notify user
            notify_recording_stopped("Silence detected - no speech")

            return ""  # Return empty string instead of None

        # Create transcript entry
        if recording_id:
            try:
                db.create_transcript(
                    recording_id=recording_id,
                    text=result.text,
                    language=result.language,
                    model_used=config.openai.model,
                    confidence=None,  # Whisper API doesn't always provide this
                )
                transcript_stored = True
                logging.debug(f"Created transcript entry for recording {recording_id}")
            except Exception as e:
                logging.warning(f"Failed to create transcript entry: {e}")

        # Copy to clipboard (only if not silence-detected)
        if not result.silence_detected:
            clipboard = ClipboardManager()
            clipboard.copy_to_clipboard(result.text)

        logging.info(f"Transcription completed: {result.text}")
        notify_recording_stopped(result.text)

        return result.text

    except Exception as e:
        logging.error(f"Transcription error: {e}")
        notify_error(f"Transcription failed: {e}")

        # Remove the in-progress recording row so failed transcriptions do not
        # leave orphaned rows in history. Rows with persisted audio or a stored
        # transcript are kept - deleting those would orphan real data.
        if db is not None and recording_id and not audio_saved and not transcript_stored:
            try:
                if db.delete_recording(recording_id):
                    logging.info(
                        f"Removed in-progress recording entry {recording_id}"
                    )
            except Exception as cleanup_error:
                logging.warning(
                    f"Failed to clean up in-progress recording entry: {cleanup_error}"
                )

        return None

    finally:
        # Close database connection
        if db is not None:
            db.close()
        # Clean up audio file (it's been saved to persistent storage)
        if AUDIO_FILE.exists():
            AUDIO_FILE.unlink()


def main():
    """Main function - real toggle recording."""
    setup_logging()

    try:
        # Ensure dunst is running for notifications
        if not ensure_dunst_running():
            logging.warning(
                "Dunst notification daemon not available - notifications may not work"
            )

        config = load_config()

        if is_recording(config):
            logging.info("Stopping recording...")
            notify_stopping_transcription()
            if not notify_recording_stop():
                logging.warning("Failed to replace persistent notification")
            success, recording_id = stop_background_recording(config)
            if success:
                transcribe_audio(config, recording_id)
            else:
                logging.error("Failed to stop recording properly")
        else:
            # Start new recording
            process = start_background_recording(config)
            if process is None:
                logging.error("Failed to start recording")
                sys.exit(1)

    except Exception as e:
        logging.error(f"Error: {e}")
        notify_error(str(e))
        # Clean up on error
        stop_background_recording(config)
        if AUDIO_FILE.exists():
            AUDIO_FILE.unlink()


if __name__ == "__main__":
    main()
