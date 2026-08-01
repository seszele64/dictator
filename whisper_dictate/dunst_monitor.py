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
- USED BY: toggle_dictate.py and other modules that need notifications

🧠 ADHD CONTEXT: Prevents the frustration of "why aren't notifications working?"
by ensuring the notification system is always available when needed.
"""

import logging
import subprocess
import time


class DunstMonitor:
    """
    WHY THIS EXISTS: Provides a centralized way to ensure dunst is running
    before attempting to send notifications.

    RESPONSIBILITY: Check dunst status and start it if necessary.

    BOUNDARIES:
    - DOES: Check if dunst is running, start dunst if not found
    - DOES NOT: Monitor dunst health after startup or handle crashes
    """

    def __init__(self):
        """Initialize the DunstMonitor."""
        self.logger = logging.getLogger(__name__)

    def is_dunst_running(self) -> bool:
        """
        WHY THIS EXISTS: Need to check if dunst daemon is currently running
        before attempting notifications.

        RESPONSIBILITY: Check system process list for running dunst instances.

        Returns:
            bool: True if dunst is running, False otherwise
        """
        try:
            # Check for dunst processes
            result = subprocess.run(
                ['pgrep', '-f', 'dunst'],
                capture_output=True,
                text=True,
                check=False
            )
            return result.returncode == 0 and result.stdout.strip() != ""

        except FileNotFoundError:
            # pgrep not available, try alternative
            try:
                result = subprocess.run(
                    ['ps', 'aux'],
                    capture_output=True,
                    text=True,
                    check=False
                )
                return 'dunst' in result.stdout.lower()
            except Exception:
                return False
        except Exception as e:
            self.logger.warning(f"Error checking dunst status: {e}")
            return False

    def start_dunst(self) -> bool:
        """
        WHY THIS EXISTS: When dunst isn't running, we need to start it
        to ensure notifications work properly.

        RESPONSIBILITY: Start the dunst notification daemon.

        Returns:
            bool: True if dunst was started successfully, False otherwise
        """
        try:
            # Start dunst in background
            subprocess.Popen(
                ['dunst'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            # Give dunst time to start
            time.sleep(0.5)

            # Verify it started
            if self.is_dunst_running():
                self.logger.info("Dunst notification daemon started")
                return True
            else:
                self.logger.error("Failed to start dunst")
                return False

        except FileNotFoundError:
            self.logger.error("dunst command not found - is dunst installed?")
            return False
        except Exception as e:
            self.logger.error(f"Error starting dunst: {e}")
            return False

    def ensure_dunst_running(self) -> bool:
        """
        WHY THIS EXISTS: Main entry point to guarantee dunst is available
        for notifications during dictation operations.

        RESPONSIBILITY: Ensure dunst is running, starting it if necessary.

        Returns:
            bool: True if dunst is running (either already or just started), False otherwise
        """
        if self.is_dunst_running():
            self.logger.debug("Dunst is already running")
            return True

        self.logger.info("Dunst not found - attempting to start")
        return self.start_dunst()

    def get_dunst_status(self) -> dict:
        """
        WHY THIS EXISTS: Provides detailed status information for debugging
        and user feedback purposes.

        RESPONSIBILITY: Return comprehensive dunst status information.

        Returns:
            dict: Status information including running state and any errors
        """
        running = self.is_dunst_running()

        status = {
            'running': running,
            'available': self._check_dunst_binary(),
            'pid': self._get_dunst_pid() if running else None
        }

        return status

    def _check_dunst_binary(self) -> bool:
        """Check if dunst binary is available in PATH."""
        try:
            subprocess.run(
                ['which', 'dunst'],
                capture_output=True,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _get_dunst_pid(self) -> int | None:
        """Get the PID of the running dunst process."""
        try:
            result = subprocess.run(
                ['pgrep', 'dunst'],
                capture_output=True,
                text=True,
                check=True
            )
            pid_str = result.stdout.strip().split('\n')[0]
            return int(pid_str) if pid_str else None
        except Exception:
            return None


# Global instance for convenience
_dunst_monitor = None

def get_dunst_monitor() -> DunstMonitor:
    """
    WHY THIS EXISTS: Provides a singleton instance of DunstMonitor
    to avoid creating multiple instances.

    RESPONSIBILITY: Return the global DunstMonitor instance.

    Returns:
        DunstMonitor: The global monitor instance
    """
    global _dunst_monitor
    if _dunst_monitor is None:
        _dunst_monitor = DunstMonitor()
    return _dunst_monitor


def ensure_dunst_running() -> bool:
    """
    WHY THIS EXISTS: Simple wrapper function for the most common use case.

    RESPONSIBILITY: Ensure dunst is running using the global monitor.

    Returns:
        bool: True if dunst is running, False otherwise
    """
    monitor = get_dunst_monitor()
    return monitor.ensure_dunst_running()
