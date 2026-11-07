"""Tests for notification functionality."""

import unittest
from unittest.mock import Mock, patch

from whisper_dictate.notifications import (
    CLIPBOARD_FAILURE_LINE,
    PROCESSED_PREVIEW_LIMIT,
    is_dunstify_available,
    notify_error,
    notify_processed,
    notify_processing_skipped,
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


class TestNotifyProcessingSkipped:
    """Group 5: notify_processing_skipped carries the caller's reason verbatim."""

    def test_argv_and_body(self):
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            result = notify_processing_skipped("No transcript to process.")

            assert result is True
            mock_send.assert_called_once_with(
                summary="Post-processing",
                body="No transcript to process.",
                urgency="normal",
                timeout=5000,
            )

    def test_recording_reason_body(self):
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            notify_processing_skipped("Stop recording first.")

            assert mock_send.call_args.kwargs["body"] == "Stop recording first."

    def test_returns_false_when_dunstify_missing(self):
        """Best-effort: a missing dunstify returns False and never raises."""
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = False

            assert notify_processing_skipped("No transcript to process.") is False

    def test_never_raises_when_subprocess_fails(self):
        """A subprocess failure propagates as False, not an exception."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            assert notify_processing_skipped("No transcript to process.") is False


class TestNotifyProcessed:
    """Group 5: notify_processed previews the result and folds in copy failure."""

    def test_short_preview_untouched(self):
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            result = notify_processed("Short result")

            assert result is True
            mock_send.assert_called_once_with(
                summary="Processed",
                body="Short result",
                urgency="normal",
                timeout=5000,
            )

    def test_empty_preview(self):
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            notify_processed("")

            assert mock_send.call_args.kwargs["body"] == ""

    def test_long_preview_truncated_at_limit_with_ellipsis(self):
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            long_text = "x" * (PROCESSED_PREVIEW_LIMIT + 50)
            notify_processed(long_text)

            body = mock_send.call_args.kwargs["body"]
            assert body == "x" * PROCESSED_PREVIEW_LIMIT + "…"
            assert len(body) == PROCESSED_PREVIEW_LIMIT + 1

    def test_preview_exactly_at_limit_not_truncated(self):
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            exact = "y" * PROCESSED_PREVIEW_LIMIT
            notify_processed(exact)

            assert mock_send.call_args.kwargs["body"] == exact

    def test_clipboard_failure_appends_exact_line_after_blank_line(self):
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            notify_processed("Clean output", clipboard_copied=False)

            body = mock_send.call_args.kwargs["body"]
            assert body == f"Clean output\n\n{CLIPBOARD_FAILURE_LINE}"
            assert body.endswith("⚠️ Clipboard copy failed. Result saved to history.")

    def test_clipboard_failure_line_survives_preview_truncation(self):
        """Only the preview is truncated; the fixed failure line is intact."""
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            notify_processed("z" * (PROCESSED_PREVIEW_LIMIT + 100), clipboard_copied=False)

            body = mock_send.call_args.kwargs["body"]
            assert body.startswith("z" * PROCESSED_PREVIEW_LIMIT + "…")
            assert body.endswith(CLIPBOARD_FAILURE_LINE)

    def test_clipboard_copied_default_is_single_toast_without_failure_line(self):
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = True

            notify_processed("Clean output")

            body = mock_send.call_args.kwargs["body"]
            assert CLIPBOARD_FAILURE_LINE not in body

    def test_returns_false_when_dunstify_missing(self):
        with patch("whisper_dictate.notifications.send_notification") as mock_send:
            mock_send.return_value = False

            assert notify_processed("Clean output") is False

    def test_never_raises_when_subprocess_fails(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            assert notify_processed("Clean output") is False
