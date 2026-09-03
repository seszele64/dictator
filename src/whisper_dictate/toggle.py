"""
Dictation toggle for i3 - proper real-time recording with immediate start/stop.
With database integration for persistence and state management.

WHY THIS EXISTS: the toggle owns the background-recording lifecycle that no
other entry point has - spawning and killing the ``arecord`` subprocess, the
legacy PID/state dotfiles, and the start/stop state machine behind one
Super+Z keypress. The transcription half is delegated: ``transcribe_audio``
hands the recorded file to ``DictationService.transcribe_existing()``
(claim-first save, duration update, transcript rows, clipboard copy) instead
of duplicating that stack; the toggle's own raw SQL and its second
recording/transcription stack were removed in the S4 cut-over. The third
logging-setup copy (``setup_logging``) remains here and is absorbed into
``util/logging_setup.py`` by S3.
"""

import contextlib
import logging
import os
import signal
import subprocess
import sys
import time

import click

from whisper_dictate.app import bootstrap
from whisper_dictate.audio_storage import AudioStorage
from whisper_dictate.config import AppConfig, AppPaths
from whisper_dictate.database import Database
from whisper_dictate.dictation import DictationService
from whisper_dictate.dunst_monitor import ensure_dunst_running
from whisper_dictate.notifications import (
    notify_error,
    notify_recording_start,
    notify_recording_stop,
    notify_recording_stopped,
    notify_stopping_transcription,
)

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


def setup_logging() -> None:
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

    # Clear existing handlers to avoid duplicates. Close each one first so a
    # re-setup never orphans handlers that hold resources (e.g. the CLI group
    # callback's DatabaseLogHandler keeps its database open until click
    # teardown). close() is a no-op on already-closed handlers; failures are
    # swallowed so a broken stale handler cannot abort re-setup.
    for handler in root_logger.handlers[:]:
        with contextlib.suppress(Exception):
            handler.close()
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


def get_db_and_storage(config: AppConfig | None = None) -> tuple[Database, AudioStorage]:
    """Get database and audio storage instances.

    Args:
        config: Loaded application configuration. When None, configuration is
            loaded so the user's configured database paths are always honored.

    Returns:
        tuple: (database, audio_storage)
    """
    if config is None:
        # Module-level bootstrap (kept patchable for tests that redirect
        # storage paths); honors the user's configured database paths.
        config = bootstrap()
    db_config = config.database
    db = Database(db_config)
    db.initialize()
    audio_storage = AudioStorage(db_config)
    return db, audio_storage


def is_recording(config: AppConfig | None = None) -> bool:
    """Check if currently recording.

    Checks database state first, falls back to file-based state for compatibility.

    Args:
        config: Loaded application configuration (loaded when None)

    Returns:
        bool: True if recording, False otherwise.
    """
    db: Database | None = None
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


def get_recording_pid() -> int | None:
    """Get the PID of the recording process."""
    try:
        if PID_FILE.exists():
            return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        pass
    return None


def start_background_recording(config: AppConfig) -> subprocess.Popen[bytes] | None:
    """Start background recording process using arecord."""
    db: Database | None = None
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
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Save PID for later management
        PID_FILE.write_text(str(process.pid))
        STATE_FILE.touch()

        # Create recording entry in database
        recording_id: int | None = None
        try:
            db, _ = get_db_and_storage(config)
            # Create initial recording entry. An empty file_path is the
            # "no file yet" sentinel: the absolute temp path would escape the
            # recordings root, and the real path is claimed after the save.
            recording_id = db.create_recording(
                file_path="",
                duration=None,  # Will be updated on stop
                format="wav",  # the toggle always records WAV
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


def stop_background_recording(
    config: AppConfig | None = None,
) -> tuple[bool, int | None]:
    """Stop background recording and process the audio.

    Returns:
        tuple: (success: bool, recording_id: int or None) - Returns the recording_id
               before clearing it from state, so it can be used for transcription.
    """
    recording_id: int | None = None
    db: Database | None = None

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


def transcribe_audio(config: AppConfig, recording_id: int | None = None) -> str | None:
    """Transcribe the recorded audio.

    Delegates the transcribe → clipboard → database half to
    ``DictationService.transcribe_existing()`` (claim-first audio save,
    duration update, transcript rows, clipboard copy). This wrapper keeps
    only the toggle-specific AUDIO_FILE handling, the recording_id state
    fallback, and the user notifications.

    Args:
        config: Configuration object
        recording_id: Optional recording ID. If not provided, will attempt to get from state.
    """
    db: Database | None = None
    try:
        if not AUDIO_FILE.exists():
            logging.error("No audio file found")
            return None

        logging.info("Starting transcription")

        # Database only for the recording_id fallback lookup; the service
        # manages its own connection (closed by its context manager).
        db, _ = get_db_and_storage(config)

        # Get recording ID from parameter or fall back to state lookup
        if recording_id is None:
            recording_id = db.get_state(STATE_KEY_RECORDING_ID)

        # Accepted edge-only drift (S3 revisit): DictationService constructs
        # its transcriber/clipboard up-front, BEFORE the claim-first save
        # inside transcribe_existing, so in the double-failure case (save
        # fails AND construction raises) the in-progress row is left behind
        # where the old inline flow would have deleted it.
        with DictationService(config) as service:
            # copy_to_clipboard=True preserves the legacy toggle quirk of
            # always copying the transcribed text; revisit (defer to
            # config.copy_to_clipboard) with the S3 layout move.
            result = service.transcribe_existing(recording_id, AUDIO_FILE, copy_to_clipboard=True)

        # Handle silence detection for the notification/return contract
        if result.silence_detected:
            notify_recording_stopped("Silence detected - no speech")
            return ""  # Return empty string instead of None

        notify_recording_stopped(result.text)
        return result.text

    except Exception as e:
        logging.error(f"Transcription error: {e}")
        notify_error(f"Transcription failed: {e}")
        return None

    finally:
        # Close the fallback-lookup database connection
        if db is not None:
            db.close()
        # Clean up audio file (it's been saved to persistent storage)
        if AUDIO_FILE.exists():
            AUDIO_FILE.unlink()


def main() -> None:
    """Main function - real toggle recording."""
    setup_logging()

    # Bound only after a successful bootstrap; failure paths must not touch
    # an unbound/None config (the legacy script crashed with a NameError in
    # its cleanup line when startup itself failed).
    config = None
    try:
        # Ensure dunst is running for notifications
        if not ensure_dunst_running():
            logging.warning("Dunst notification daemon not available - notifications may not work")

        # Fail fast on a missing API key BEFORE recording, replicating the
        # legacy startup UX (pre-batch): load_config() defaulted to
        # require_api_key=True, so a keyless startup notified the error and
        # exited non-zero without ever spawning arecord.
        config = bootstrap(require_api_key=True)

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
        # Clean up on error (only meaningful if startup got past bootstrap)
        if config is not None:
            stop_background_recording(config)
        if AUDIO_FILE.exists():
            AUDIO_FILE.unlink()
        if config is None:
            # Startup failed before configuration existed (e.g. missing API
            # key). The legacy script exited non-zero here - its cleanup
            # line crashed on the unbound config - so exit 1 deterministically.
            sys.exit(1)


if __name__ == "__main__":
    main()


@click.command()
def cli() -> None:
    """Toggle dictation: start or stop background recording.

    Console-script entry for ``whisper-dictate-toggle``. The toggle takes
    no options, so this wrapper exists only so ``--help`` (and unknown
    arguments) are answered by click WITHOUT invoking the toggle — the
    plain ``main()`` entry would start a recording, which is a surprising
    side effect for a help flag. The dedicated click command module lands
    with the S3 split into ``cli/commands/toggle.py``.
    """
    main()
