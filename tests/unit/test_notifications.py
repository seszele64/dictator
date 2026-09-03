"""Tests for notification functionality."""

import unittest
from unittest.mock import Mock, patch

from whisper_dictate.notifications import (
    is_dunstify_available,
    notify_error,
    notify_recording_stopped,
    notify_stopping_transcription,
    send_notification,
)


class TestSendNotification(unittest.TestCase):
    """Test the send_notification function."""

    def test_send_notification_success(self):
        """Test successful notification sending."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = send_notification("Test Title", "Test Body")
            assert result is True

            mock_run.assert_called_once_with(
                [
                    "notify-send",
                    "--urgency=normal",
                    "--expire-time=5000",
                    "Test Title",
                    "Test Body",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_send_notification_with_urgency(self):
        """Test notification with custom urgency."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = send_notification("Test", "Body", urgency="critical")
            assert result is True

            mock_run.assert_called_once_with(
                [
                    "notify-send",
                    "--urgency=critical",
                    "--expire-time=5000",
                    "Test",
                    "Body",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_send_notification_with_timeout(self):
        """Test notification with custom timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = send_notification("Test", "Body", timeout=10000)
            assert result is True

            mock_run.assert_called_once_with(
                [
                    "notify-send",
                    "--urgency=normal",
                    "--expire-time=10000",
                    "Test",
                    "Body",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_send_notification_no_body(self):
        """Test notification without body text."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = send_notification("Test Title")
            assert result is True

            mock_run.assert_called_once_with(
                [
                    "notify-send",
                    "--urgency=normal",
                    "--expire-time=5000",
                    "Test Title",
                    "",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_send_notification_command_not_found(self):
        """Test handling when notify-send is not available."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            result = send_notification("Test", "Body")
            assert result is False

    def test_send_notification_subprocess_error(self):
        """Test handling of subprocess errors."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Subprocess error")

            result = send_notification("Test", "Body")
            assert result is False

    def test_send_notification_non_zero_exit(self):
        """Test handling of non-zero exit codes."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)

            result = send_notification("Test", "Body")
            assert result is False


class TestNotificationHelpers:
    """Test the notification helper functions."""

    def test_notify_recording_stopped_without_preview(self):
        """Test recording stopped notification without text preview."""
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            result = notify_recording_stopped()
            assert result is True

            mock_send.assert_called_once_with(
                summary="Dictation",
                body="Recording stopped and processing...",
                urgency="normal",
                timeout=5000,
            )

    def test_notify_recording_stopped_with_short_preview(self):
        """Test recording stopped notification with short text preview."""
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            result = notify_recording_stopped("Short text")
            assert result is True

            mock_send.assert_called_once_with(
                summary="Dictation",
                body="Transcription: Short text",
                urgency="normal",
                timeout=5000,
            )

    def test_notify_recording_stopped_with_long_preview(self):
        """Test recording stopped notification with long text preview."""
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            long_text = "This is a very long text that should be truncated to 50 characters"
            expected_preview = "This is a very long text that should be truncated..."

            result = notify_recording_stopped(long_text)
            assert result is True

            mock_send.assert_called_once_with(
                summary="Dictation",
                body=f"Transcription: {expected_preview}",
                urgency="normal",
                timeout=5000,
            )

    def test_notify_error(self):
        """Test error notification."""
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            result = notify_error("Something went wrong")
            assert result is True

            mock_send.assert_called_once_with(
                summary="Dictation Error",
                body="Something went wrong",
                urgency="critical",
                timeout=10000,
            )

    def test_notify_stopping_transcription(self):
        """Test stopping transcription notification."""
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            result = notify_stopping_transcription()
            assert result is True

            mock_send.assert_called_once_with(
                summary="Dictation",
                body="Stopping recording... processing audio",
                urgency="normal",
                timeout=2000,
            )

    def test_notification_helpers_failure_handling(self):
        """Test that helper functions properly handle send_notification failures."""
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = False

            assert notify_recording_stopped() is False
            assert notify_error("test") is False
            assert notify_stopping_transcription() is False


class TestIsDunstifyAvailable:
    """Test the is_dunstify_available function."""

    def test_dunstify_available(self):
        """Test when dunstify is available."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/dunstify"

            result = is_dunstify_available()
            assert result is True
            mock_which.assert_called_once_with("dunstify")

    def test_dunstify_not_available(self):
        """Test when dunstify is not available."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None

            result = is_dunstify_available()
            assert result is False
            mock_which.assert_called_once_with("dunstify")
