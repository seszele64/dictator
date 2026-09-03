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
- USED BY: whisper_dictate/toggle.py and other modules that need user feedback

🧠 ADHD CONTEXT: Having a single, well-documented function for notifications
prevents the cognitive load of remembering notify-send syntax and parameters.
"""

import logging
import shutil
import subprocess
from typing import Literal

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
            logger.warning("dunstify not available, cannot send persistent notification")
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

        logger.info("Recording stop notification sent (replaced persistent notification)")
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
        preview = text_preview[:49] + "..." if len(text_preview) > 52 else text_preview  # 49 + 3 = 52 total
        body = f"Transcription: {preview}"

    return send_notification(summary="Dictation", body=body, urgency="normal", timeout=5000)


def notify_error(error_message: str) -> bool:
    """
    WHY THIS EXISTS: Standardized error notifications for consistent user feedback.

    RESPONSIBILITY: Send a consistent error notification with the provided message.

    Args:
        error_message: The error description to display

    Returns:
        bool: True if notification sent successfully
    """
    return send_notification(summary="Dictation Error", body=error_message, urgency="critical", timeout=10000)


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
