#!/usr/bin/env python3
"""
WHY THIS EXISTS: Dunst notifications are critical for user feedback during dictation,
but dunst might not always be running (e.g., after system restart, session changes).
This ensures dunst is available before attempting notifications.

RESPONSIBILITY: Monitor and ensure dunst notification daemon is running.

BOUNDARIES:
- DOES: Check dunst status, start dunst if needed, provide status feedback
- DOES NOT: Manage dunst configuration or handle dunst crashes after startup
- DEPENDS ON: dunst binary being available in system PATH
- USED BY: whisper_dictate/toggle.py and other modules that need notifications

🧠 ADHD CONTEXT: Prevents the frustration of "why aren't notifications working?"
by ensuring the notification system is always available when needed.
"""

import logging
import subprocess
import time

# Set up module-level logger
logger = logging.getLogger(__name__)


def is_dunst_running() -> bool:
    """
    WHY THIS EXISTS: Need to check if dunst daemon is currently running
    before attempting notifications.

    RESPONSIBILITY: Check system process list for running dunst instances.

    Returns:
        bool: True if dunst is running, False otherwise
    """
    try:
        # Check for dunst processes
        result = subprocess.run(["pgrep", "-f", "dunst"], capture_output=True, text=True, check=False)
        return result.returncode == 0 and result.stdout.strip() != ""

    except FileNotFoundError:
        # pgrep not available, try alternative
        try:
            result = subprocess.run(["ps", "aux"], capture_output=True, text=True, check=False)
            return "dunst" in result.stdout.lower()
        except Exception:
            return False
    except Exception as e:
        logger.warning(f"Error checking dunst status: {e}")
        return False


def start_dunst() -> bool:
    """
    WHY THIS EXISTS: When dunst isn't running, we need to start it
    to ensure notifications work properly.

    RESPONSIBILITY: Start the dunst notification daemon.

    Returns:
        bool: True if dunst was started successfully, False otherwise
    """
    try:
        # Start dunst in background
        subprocess.Popen(["dunst"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

        # Give dunst time to start
        time.sleep(0.5)

        # Verify it started
        if is_dunst_running():
            logger.info("Dunst notification daemon started")
            return True
        else:
            logger.error("Failed to start dunst")
            return False

    except FileNotFoundError:
        logger.error("dunst command not found - is dunst installed?")
        return False
    except Exception as e:
        logger.error(f"Error starting dunst: {e}")
        return False


def ensure_dunst_running() -> bool:
    """
    WHY THIS EXISTS: Main entry point to guarantee dunst is available
    for notifications during dictation operations.

    RESPONSIBILITY: Ensure dunst is running, starting it if necessary.

    Returns:
        bool: True if dunst is running (either already or just started), False otherwise
    """
    if is_dunst_running():
        logger.debug("Dunst is already running")
        return True

    logger.info("Dunst not found - attempting to start")
    return start_dunst()
