#!/usr/bin/env python3
"""
WHY THIS EXISTS: i3 notifications are used throughout the application to provide
user feedback for recording states, transcription results, and error conditions.
Centralizing this prevents inconsistent notification styling and makes it easier
to maintain notification behavior across the application.

RESPONSIBILITY: Provide a clean, type-safe interface for sending desktop notifications
in i3 window manager environments.

BOUNDARIES:
- DOES: Send desktop notifications with configurable urgency, timeout, and content
- DOES NOT: Handle notification history, interactive notifications, or sound alerts
- DEPENDS ON: notify-send command being available in the system
- USED BY: toggle_dictate.py and other modules that need user feedback

🧠 ADHD CONTEXT: Having a single, well-documented function for notifications
prevents the cognitive load of remembering notify-send syntax and parameters.

T5b ACTION BUTTON FEATURE (FR-005):
-----------------------------------
Persistent notifications can include action buttons that users can click to
trigger actions. This is implemented using dunstify's -A flag.

How to use the Stop Recording action:
1. A notification appears with a "Stop Recording" action button
2. Press Ctrl+Shift+. to open dunst's context menu (requires i3 keybinding below)
3. Select "Stop Recording" from the menu
4. The action callback is triggered

PREREQUISITES:
- dunst notification daemon must be running
- dmenu must be installed (used by dunst for context menu)
- i3 keybinding: Add "bindsym Ctrl+Shift+. exec dunstctl context" to ~/.config/i3/config
- Reload i3 with: i3-msg reload

NOTE: The action button requires the dunst context menu to be enabled via
the dunstctl context command. The default keybinding is Ctrl+Shift+. but
can be customized in your dunst configuration.
"""

import logging
import shutil
import subprocess
import time
from typing import Literal, Optional

# Stack tag for recording notifications - replaces ID-based persistence
# Using stack tags is the recommended approach by dunst maintainers
# as it works across process invocations and avoids ID tracking issues
RECORDING_STACK_TAG = "whisper-dictate-recording"

# Set up module-level logger
logger = logging.getLogger(__name__)


def notify_recording_start() -> bool:
    """
    Send a persistent notification when recording starts using stack tags.

    Uses dunst stack tags (x-dunst-stack-tag hint) instead of tracking
    notification IDs. This approach is recommended by dunst maintainers
    because:
    - Works across script invocations and different processes
    - No need to track/load/save notification IDs
    - Notifications with same stack tag automatically replace each other

    Returns:
        bool: True if notification was sent successfully
    """
    try:
        if not is_dunstify_available():
            logger.warning(
                "dunstify not available, cannot send persistent notification"
            )
            return False

        cmd = [
            "dunstify",
            "-h",
            f"string:x-dunst-stack-tag:{RECORDING_STACK_TAG}",
            "-t",
            "0",  # Persistent (0 = infinite)
            "-u",
            "critical",  # Red color for recording
            "Recording",
            "Dictation in progress...",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            logger.error(
                "Failed to send recording notification: %s",
                result.stderr.strip() if result.stderr else "unknown error",
            )
            return False

        logger.info("Recording notification sent (stack tag: %s)", RECORDING_STACK_TAG)
        return True

    except FileNotFoundError:
        logger.error("dunstify not found")
        return False
    except Exception as e:
        logger.error("Failed to send recording notification: %s", e)
        return False


def notify_recording_stop() -> bool:
    """
    Replace the persistent recording notification with a brief "stopped" message.

    Uses the same stack tag to automatically replace the persistent notification.
    The new notification has a short timeout so it disappears after 2 seconds.

    Returns:
        bool: True if notification was sent successfully
    """
    try:
        if not is_dunstify_available():
            logger.warning("dunstify not available, cannot send stop notification")
            return False

        cmd = [
            "dunstify",
            "-h",
            f"string:x-dunst-stack-tag:{RECORDING_STACK_TAG}",
            "-t",
            "2000",  # 2 second timeout
            "-u",
            "normal",
            "Recording Stopped",
            "Transcription in progress...",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            logger.error(
                "Failed to send stop notification: %s",
                result.stderr.strip() if result.stderr else "unknown error",
            )
            return False

        logger.info(
            "Recording stop notification sent (replaced persistent notification)"
        )
        return True

    except FileNotFoundError:
        logger.error("dunstify not found")
        return False
    except Exception as e:
        logger.error("Failed to send stop notification: %s", e)
        return False


# Type aliases for notification parameters
UrgencyLevel = Literal["low", "normal", "critical"]
TimeoutMs = int  # Timeout in milliseconds


def is_dunstify_available() -> bool:
    """
    Check if dunstify binary is available on the system.

    RESPONSIBILITY: Determine whether dunstify can be used for notifications.

    Returns:
        bool: True if dunstify binary exists, False otherwise
    """
    return shutil.which("dunstify") is not None


def send_notification(
    summary: str,
    body: str = "",
    urgency: UrgencyLevel = "normal",
    timeout: TimeoutMs = 5000,
) -> bool:
    """
    WHY THIS EXISTS: Provides a consistent way to send desktop notifications
    across the application with proper error handling and type safety.

    RESPONSIBILITY: Send a desktop notification using notify-send command.

    DOES:
    - Send notifications with configurable urgency and timeout
    - Handle command execution errors gracefully
    - Provide boolean success/failure feedback

    DOES NOT:
    - Queue notifications if system is busy
    - Handle notification server unavailability
    - Provide notification history or callbacks

    Args:
        summary: The notification title/summary text
        body: Optional detailed message body
        urgency: Notification urgency level ("low", "normal", or "critical")
        timeout: Display duration in milliseconds (0 for persistent)

    Returns:
        bool: True if notification was sent successfully, False otherwise

    Examples:
        >>> send_notification("Recording Started", "Press again to stop")
        True
        >>> send_notification("Error", "Failed to start recording", "critical", 10000)
        True
    """
    try:
        cmd = [
            "notify-send",
            f"--urgency={urgency}",
            f"--expire-time={timeout}",
            summary,
            body,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,  # Don't raise exception on non-zero exit
        )

        return result.returncode == 0

    except FileNotFoundError:
        # notify-send command not found
        return False
    except Exception:
        # Other subprocess errors
        return False


def notify_recording_stopped(text_preview: str = "") -> bool:
    """
    WHY THIS EXISTS: Standardized notification for when recording stops.

    RESPONSIBILITY: Send a consistent "recording stopped" notification with
    optional transcription preview.

    Args:
        text_preview: First part of transcribed text to show

    Returns:
        bool: True if notification sent successfully
    """
    body = "Recording stopped and processing..."
    if text_preview:
        if len(text_preview) > 52:
            preview = text_preview[:49] + "..."  # 49 + 3 = 52 total
        else:
            preview = text_preview
        body = f"Transcription: {preview}"

    return send_notification(
        summary="Dictation", body=body, urgency="normal", timeout=5000
    )


def notify_error(error_message: str) -> bool:
    """
    WHY THIS EXISTS: Standardized error notifications for consistent user feedback.

    RESPONSIBILITY: Send a consistent error notification with the provided message.

    Args:
        error_message: The error description to display

    Returns:
        bool: True if notification sent successfully
    """
    return send_notification(
        summary="Dictation Error", body=error_message, urgency="critical", timeout=10000
    )


def notify_stopping_transcription() -> bool:
    """
    WHY THIS EXISTS: Provides immediate user feedback when recording is stopped
    and transcription is about to begin, preventing confusion about whether
    the key press was registered.

    RESPONSIBILITY: Send a consistent "stopping recording" notification.

    Returns:
        bool: True if notification sent successfully
    """
    return send_notification(
        summary="Dictation",
        body="Stopping recording... processing audio",
        urgency="normal",
        timeout=2000,
    )


def is_dunst_running() -> bool:
    """
    Check if the dunst notification daemon is currently running.

    RESPONSIBILITY: Verify that the notification daemon is alive and can
    receive commands. This is critical for detecting daemon crashes.

    Returns:
        bool: True if dunst process is running, False otherwise
    """
    try:
        # Check if dunst process exists
        result = subprocess.run(
            ["pgrep", "-x", "dunst"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


class PersistentNotification:
    """
    Manages a persistent notification that stays visible during recording.

    Uses dunstify with stack tags to allow updates and closing.

    EDGE CASE HANDLING:
    - Multiple rapid start/stop: Uses rate limiting to prevent race conditions
    - Daemon crash: Tracks consecutive failures and attempts recovery
    - Stale notification IDs: Validates daemon state before operations
    """

    _last_operation_time: float = 0.0
    _min_operation_interval: float = 0.1  # Minimum 100ms between operations

    def __init__(self, stack_tag: str = "dictation-recording"):
        """Initialize the persistent notification manager."""
        self.stack_tag = stack_tag
        self.notification_id: Optional[str] = None
        self._is_active: bool = False
        self.summary: str = "Dictation"
        self.urgency: UrgencyLevel = "critical"
        # Track consecutive failures for daemon crash detection
        self._consecutive_failures: int = 0
        self._max_consecutive_failures: int = 3
        self._last_known_daemon_state: bool = True

    def send(
        self,
        summary: str,
        body: str,
        urgency: UrgencyLevel = "critical",
        wait_for_action: bool = False,
    ) -> Optional[str]:
        """Send a persistent notification with -t 0 for indefinite display.

        EDGE CASE 1: Multiple Rapid Start/Stop
        - Implements rate limiting using _last_operation_time and _min_operation_interval
        - If too soon after last operation, skip the action to prevent race conditions

        EDGE CASE 2: Notification Daemon Crash During Recording
        - Tracks consecutive failures to detect daemon crashes
        - On success: resets failure counter to 0
        - On failure: increments failure counter

        Args:
            summary: The notification title
            body: The notification body text
            urgency: The urgency level (default: critical)
            wait_for_action: If True, block until user clicks an action button.
                             Requires running in blocking mode. Default is False.

        Returns:
            Optional[str]: Notification ID if successful, None otherwise.
                          If wait_for_action=True, returns action name clicked.
        """
        self.summary = summary
        self.urgency = urgency

        if self._is_active:
            return self.update(body)

        if not is_dunstify_available():
            logger.warning("dunstify not available, falling back")
            return None

        # EDGE CASE: Rate limiting - check if enough time has passed since last operation
        current_time = time.time()
        elapsed = current_time - PersistentNotification._last_operation_time
        if elapsed < PersistentNotification._min_operation_interval:
            logger.debug(
                f"Rate limiting: skipping send, only {elapsed:.3f}s since last operation"
            )
            return None

        cmd = [
            "dunstify",
            "-u",
            urgency,
            "-t",
            "0",  # 0 = persistent/infinite
            "-p",  # Print notification ID
        ]

        # T5b: Add action button for stopping recording
        # The action appears in dunst's context menu (Ctrl+Shift+.)
        # When clicked, dunstify outputs the action name to stdout
        cmd.extend(["-A", "stop,Stop Recording"])

        # T5b: Optionally wait for user action
        # This blocks until user clicks the action button
        if wait_for_action:
            cmd.append("-w")

        cmd.extend([summary, body])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            # Update last operation time regardless of success/failure
            PersistentNotification._last_operation_time = time.time()

            # Guard against empty dunstify output
            output_lines = result.stdout.strip().splitlines()
            if not output_lines:
                self._consecutive_failures += 1
                logger.error("dunstify returned empty output")
                return None

            output = output_lines[0]

            # T5b: Handle action callback
            # When user clicks action button, dunstify returns the action name
            # The output could be either notification ID or action name
            output = result.stdout.strip().splitlines()[0]

            if result.returncode == 0 and output:
                # Check if this is an action response (e.g., "stop")
                # or a notification ID (numeric string)
                if output == "stop":
                    logger.info("User clicked Stop Recording action")
                    # Close the notification and signal stop
                    self.close()
                    return "stop"

                # Normal notification ID
                self.notification_id = output
                self._is_active = True
                # EDGE CASE 2: Reset failure counter on success
                self._consecutive_failures = 0
                self._last_known_daemon_state = True
                logger.info(f"Persistent notification sent: {self.notification_id}")
                return self.notification_id

            # EDGE CASE 2: Track failure
            self._consecutive_failures += 1
            logger.error(
                f"Failed to send persistent notification (failure #{self._consecutive_failures}): {result.stderr}"
            )
            return None
        except Exception as e:
            # EDGE CASE 2: Track failure
            PersistentNotification._last_operation_time = time.time()
            self._consecutive_failures += 1
            logger.error(
                f"Error sending persistent notification (failure #{self._consecutive_failures}): {e}"
            )
            return None

    def update(self, body: str) -> Optional[str]:
        """Update the notification body using notification ID.

        EDGE CASE: Notification Daemon Crash During Recording
        - Checks daemon health before attempting update
        - If daemon appears crashed (update fails), marks notification as inactive
        - Tracks failures similarly to send()
        """
        if not self._is_active or not self.notification_id:
            logger.warning("No active notification to update")
            return None

        # EDGE CASE: Check daemon health before attempting update
        if not is_dunst_running():
            logger.warning(
                "Notification daemon not running, marking notification as inactive"
            )
            self._is_active = False
            self._last_known_daemon_state = False
            self._consecutive_failures += 1
            PersistentNotification._last_operation_time = time.time()
            return None

        cmd = [
            "dunstify",
            "-u",
            self.urgency,
            "-t",
            "0",
            "-r",
            self.notification_id,
            self.summary,
            body,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            PersistentNotification._last_operation_time = time.time()

            if result.returncode == 0:
                if result.stdout.strip():
                    self.notification_id = result.stdout.strip()
                # EDGE CASE 2: Reset failure counter on success
                self._consecutive_failures = 0
                self._last_known_daemon_state = True
                return self.notification_id

            # EDGE CASE 2: Track failure and mark as inactive if daemon crashed
            self._consecutive_failures += 1
            logger.error(
                f"Failed to update notification (failure #{self._consecutive_failures}): {result.stderr}"
            )
            # If we've had multiple consecutive failures, assume daemon crashed
            if self._consecutive_failures >= self._max_consecutive_failures:
                logger.warning(
                    "Too many failures, assuming daemon crashed, marking inactive"
                )
                self._is_active = False
                self._last_known_daemon_state = False
            return None
        except Exception as e:
            PersistentNotification._last_operation_time = time.time()
            self._consecutive_failures += 1
            logger.error(
                f"Error updating notification (failure #{self._consecutive_failures}): {e}"
            )
            if self._consecutive_failures >= self._max_consecutive_failures:
                self._is_active = False
                self._last_known_daemon_state = False
            return None

    def close(self) -> bool:
        """Close the persistent notification using -C flag."""
        if not self._is_active:
            logger.info("Close: notification not active, skipping")
            return True

        if not is_dunstify_available():
            logger.warning("dunstify not available - cannot close notification")
            return True

        logger.info(
            f"Closing notification {self.notification_id} with command: dunstify -C {self.notification_id}"
        )

        cmd = ["dunstify", "-C", str(self.notification_id)]

        try:
            result = subprocess.run(cmd, capture_output=True, check=False)
            self._is_active = False
            self.notification_id = None
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Error closing notification: {e}")
            self._is_active = False
            return False


# Module-level instance for recording notifications
_recording_notification: Optional[PersistentNotification] = None


def notify_recording_persistent_start() -> bool:
    """Send a persistent notification when recording starts.

    T5b FEATURE: The notification includes a "Stop Recording" action button.
    To use the action button:
    1. The notification appears with a stop action
    2. Press Ctrl+Shift+. in dunst to open context menu
    3. Select "Stop Recording" to stop the recording

    Note: This requires the script to be run in blocking mode (wait_for_action=True)
    for the action callback to be handled. In the default non-blocking mode,
    the action button is displayed but the callback cannot be received.
    """
    global _recording_notification
    _recording_notification = PersistentNotification()
    result = _recording_notification.send(
        summary="Dictation",
        body="Recording in progress... press again to stop\n"
        "Or use context menu (Ctrl+Shift+.) to stop",
    )
    return result is not None


def notify_recording_persistent_start_blocking() -> Optional[str]:
    """Send a persistent notification and wait for user to click stop action.

    T5b IMPLEMENTATION: This function sends a persistent notification with
    a stop action button and blocks until the user clicks it.

    Use this for scenarios where you want the notification action to work:
    - Notification appears with "Stop Recording" button
    - User presses Ctrl+Shift+. to open dunst context menu
    - User clicks "Stop Recording"
    - Function returns "stop" to signal the recording should stop

    Returns:
        Optional[str]: "stop" if user clicked stop action, notification ID if successful, None otherwise
    """
    global _recording_notification
    _recording_notification = PersistentNotification()
    result = _recording_notification.send(
        summary="Dictation",
        body="Recording in progress... click Stop Recording to end",
        wait_for_action=True,
    )
    # If user clicked stop action, result will be "stop"
    if result == "stop":
        _recording_notification = None
        return "stop"

    return result


def notify_recording_persistent_update(text: str) -> bool:
    """Update the persistent notification with transcription text."""
    global _recording_notification
    if _recording_notification and _recording_notification._is_active:
        preview = text[:100] + "..." if len(text) > 100 else text
        result = _recording_notification.update(f"Recording... {preview}")
        return result is not None
    return False


def notify_recording_persistent_stop() -> bool:
    """Close the persistent notification when recording stops."""
    global _recording_notification
    logger.info(
        f"notify_recording_persistent_stop called: _recording_notification={_recording_notification}"
    )

    if _recording_notification and _recording_notification._is_active:
        result = _recording_notification.close()
        _recording_notification = None
        return result

    logger.warning(
        "No active notification to close (may have already been dismissed)"
    )
    return False
