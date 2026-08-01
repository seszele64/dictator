"""Tests for notification functionality."""

import unittest
from unittest.mock import Mock, patch

from whisper_dictate.notifications import (
    PersistentNotification,
    is_dunstify_available,
    notify_error,
    notify_recording_persistent_start,
    notify_recording_persistent_start_blocking,
    notify_recording_persistent_stop,
    notify_recording_persistent_update,
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

            long_text = (
                "This is a very long text that should be truncated to 50 characters"
            )
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


class TestPersistentNotification(unittest.TestCase):
    """Test the PersistentNotification class."""

    def test_init_default_stack_tag(self):
        """Test initialization with default stack_tag."""
        notification = PersistentNotification()

        assert notification.stack_tag == "dictation-recording"
        assert notification.notification_id is None
        assert notification._is_active is False
        assert notification.summary == "Dictation"
        assert notification.urgency == "critical"

    def test_init_custom_stack_tag(self):
        """Test initialization with custom stack_tag."""
        notification = PersistentNotification(stack_tag="custom-tag")

        assert notification.stack_tag == "custom-tag"
        assert notification.notification_id is None
        assert notification._is_active is False

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_send_success(self, mock_run, mock_dunstify_available):
        """Test successful notification sending."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        notification = PersistentNotification()
        result = notification.send("Test Title", "Test Body")

        assert result == "12345"
        assert notification.notification_id == "12345"
        assert notification._is_active is True
        assert notification.summary == "Test Title"
        assert notification.urgency == "critical"

        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-p",
                "-A",
                "stop,Stop Recording",
                "Test Title",
                "Test Body",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_send_with_custom_urgency(self, mock_run, mock_dunstify_available):
        """Test sending notification with custom urgency."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        notification = PersistentNotification()
        result = notification.send("Test Title", "Test Body", urgency="normal")

        assert result == "12345"
        assert notification.urgency == "normal"

        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "normal",
                "-t",
                "0",
                "-p",
                "-A",
                "stop,Stop Recording",
                "Test Title",
                "Test Body",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("whisper_dictate.notifications.is_dunstify_available")
    def test_send_dunstify_not_available(self, mock_dunstify_available):
        """Test sending when dunstify is not available."""
        mock_dunstify_available.return_value = False

        notification = PersistentNotification()
        result = notification.send("Test Title", "Test Body")

        assert result is None
        assert notification._is_active is False

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_send_failure(self, mock_run, mock_dunstify_available):
        """Test sending notification with subprocess failure."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error")

        notification = PersistentNotification()
        result = notification.send("Test Title", "Test Body")

        assert result is None
        assert notification._is_active is False

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_send_exception(self, mock_run, mock_dunstify_available):
        """Test sending notification with exception."""
        mock_dunstify_available.return_value = True
        mock_run.side_effect = Exception("Subprocess error")

        notification = PersistentNotification()
        result = notification.send("Test Title", "Test Body")

        assert result is None
        assert notification._is_active is False

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_send_when_already_active(self, mock_run, mock_dunstify_available):
        """Test sending when notification is already active (should update)."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        notification = PersistentNotification()
        notification.send("Test Title", "Test Body")

        # Reset mock to track the update call
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        result = notification.send("Test Title", "Updated Body")

        # Should call update instead of send
        assert result == "12345"
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-r",
                "12345",
                "Test Title",
                "Updated Body",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_update_success(self, mock_run, mock_dunstify_available):
        """Test successful notification update."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        notification = PersistentNotification()
        notification.send("Test Title", "Test Body")

        # Reset mock to track the update call
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        result = notification.update("Updated Body")

        assert result == "12345"
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-r",
                "12345",
                "Test Title",
                "Updated Body",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_update_not_active(self):
        """Test update when notification is not active."""
        notification = PersistentNotification()

        result = notification.update("Updated Body")

        assert result is None

    def test_update_no_notification_id(self):
        """Test update when notification_id is None."""
        notification = PersistentNotification()
        notification._is_active = True
        notification.notification_id = None

        result = notification.update("Updated Body")

        assert result is None

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_update_failure(self, mock_run, mock_dunstify_available):
        """Test update with subprocess failure."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        notification = PersistentNotification()
        notification.send("Test Title", "Test Body")

        # Reset mock to simulate failure
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error")

        result = notification.update("Updated Body")

        assert result is None

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_close_success(self, mock_run, mock_dunstify_available):
        """Test successful notification close."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        notification = PersistentNotification()
        notification.send("Test Title", "Test Body")

        # Reset mock to track the close call
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0)

        result = notification.close()

        assert result is True
        assert notification._is_active is False
        assert notification.notification_id is None
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-C",
                "12345",
            ],
            capture_output=True,
            check=False,
        )

    def test_close_not_active(self):
        """Test close when notification is not active."""
        notification = PersistentNotification()

        result = notification.close()

        assert result is True

    @patch("whisper_dictate.notifications.is_dunstify_available")
    def test_close_dunstify_not_available(self, mock_dunstify_available):
        """Test close when dunstify is not available."""
        mock_dunstify_available.return_value = False

        notification = PersistentNotification()
        notification._is_active = True
        notification.notification_id = "12345"

        result = notification.close()

        assert result is True  # Returns True (nothing to close)
        assert notification._is_active is True  # Still active (couldn't close)

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_close_failure(self, mock_run, mock_dunstify_available):
        """Test close with subprocess failure."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        notification = PersistentNotification()
        notification.send("Test Title", "Test Body")

        # Reset mock to simulate failure
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=1)

        result = notification.close()

        assert result is False
        assert notification._is_active is False
        assert notification.notification_id is None

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_close_exception(self, mock_run, mock_dunstify_available):
        """Test close with exception."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        notification = PersistentNotification()
        notification.send("Test Title", "Test Body")

        # Reset mock to simulate exception
        mock_run.reset_mock()
        mock_run.side_effect = Exception("Subprocess error")

        result = notification.close()

        assert result is False
        assert notification._is_active is False

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_send_action_callback_returns_stop(self, mock_run, mock_dunstify_available):
        """Test that send() returns 'stop' when user clicks action button."""
        mock_dunstify_available.return_value = True
        # Simulate user clicking the stop action button - dunstify returns "stop"
        mock_run.return_value = Mock(returncode=0, stdout="stop\n", stderr="")

        notification = PersistentNotification()
        result = notification.send("Test Title", "Test Body")

        assert result == "stop"
        # Notification should be closed
        assert notification._is_active is False

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_send_blocking_mode_adds_wait_flag(self, mock_run, mock_dunstify_available):
        """Test that -w flag is added when wait_for_action=True."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        notification = PersistentNotification()
        result = notification.send("Test Title", "Test Body", wait_for_action=True)

        assert result == "12345"
        # Verify -w flag is in the command
        call_args = mock_run.call_args[0][0]
        assert "-w" in call_args

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_send_empty_dunstify_output(self, mock_run, mock_dunstify_available):
        """Test send() when dunstify returns empty stdout."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(stdout="", stderr="", returncode=0)

        notification = PersistentNotification()
        with self.assertLogs("whisper_dictate.notifications", level="ERROR") as cm:
            result = notification.send("Test", "Message")

        assert result is None
        assert notification._consecutive_failures == 1
        assert "empty" in cm.output[0].lower()


class TestPersistentNotificationHelpers:
    """Test the persistent notification helper functions."""

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_notify_recording_persistent_start_success(
        self, mock_run, mock_dunstify_available
    ):
        """Test starting persistent notification."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        result = notify_recording_persistent_start()

        assert result is True
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-p",
                "-A",
                "stop,Stop Recording",
                "Dictation",
                "Recording in progress... press again to stop\nOr use context menu (Ctrl+Shift+.) to stop",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("whisper_dictate.notifications.is_dunstify_available")
    def test_notify_recording_persistent_start_failure(self, mock_dunstify_available):
        """Test starting persistent notification when dunstify not available."""
        mock_dunstify_available.return_value = False

        result = notify_recording_persistent_start()

        assert result is False

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_notify_recording_persistent_start_blocking_success(
        self, mock_run, mock_dunstify_available
    ):
        """Test blocking persistent notification returns notification ID on success."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        import whisper_dictate.notifications as notifications

        # Reset global state
        notifications._recording_notification = None

        result = notify_recording_persistent_start_blocking()

        assert result == "12345"
        # Verify wait_for_action=True is passed (should include -w flag)
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-p",
                "-A",
                "stop,Stop Recording",
                "-w",
                "Dictation",
                "Recording in progress... click Stop Recording to end",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_notify_recording_persistent_start_blocking_returns_stop(
        self, mock_run, mock_dunstify_available
    ):
        """Test blocking persistent notification returns 'stop' when user clicks action."""
        mock_dunstify_available.return_value = True
        # Simulate user clicking the stop action button
        mock_run.return_value = Mock(returncode=0, stdout="stop\n", stderr="")

        import whisper_dictate.notifications as notifications

        # Reset global state
        notifications._recording_notification = None

        result = notify_recording_persistent_start_blocking()

        assert result == "stop"

    @patch("whisper_dictate.notifications.is_dunstify_available")
    def test_notify_recording_persistent_start_blocking_failure(
        self, mock_dunstify_available
    ):
        """Test blocking persistent notification when dunstify not available."""
        mock_dunstify_available.return_value = False

        import whisper_dictate.notifications as notifications

        # Reset global state
        notifications._recording_notification = None

        result = notify_recording_persistent_start_blocking()

        assert result is None

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_notify_recording_persistent_update_success(
        self, mock_run, mock_dunstify_available
    ):
        """Test updating persistent notification."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        # First start the notification
        notify_recording_persistent_start()

        # Reset mock to track the update call
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        result = notify_recording_persistent_update("Test transcription text")

        assert result is True
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-r",
                "12345",
                "Dictation",
                "Recording... Test transcription text",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_notify_recording_persistent_update_long_text(
        self, mock_run, mock_dunstify_available
    ):
        """Test updating with long text (should be truncated)."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        # First start the notification
        notify_recording_persistent_start()

        # Reset mock to track the update call
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        long_text = "a" * 150
        result = notify_recording_persistent_update(long_text)

        assert result is True
        expected_preview = "a" * 100 + "..."
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-r",
                "12345",
                "Dictation",
                f"Recording... {expected_preview}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_notify_recording_persistent_update_not_active(self):
        """Test updating when notification is not active."""
        # Reset the global notification state
        import whisper_dictate.notifications as notifications

        notifications._recording_notification = None

        result = notify_recording_persistent_update("Test text")

        assert result is False

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_notify_recording_persistent_stop_success(
        self, mock_run, mock_dunstify_available
    ):
        """Test stopping persistent notification."""
        mock_dunstify_available.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        # First start the notification
        notify_recording_persistent_start()

        # Reset mock to track the close call
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0)

        result = notify_recording_persistent_stop()

        assert result is True
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-C",
                "12345",
            ],
            capture_output=True,
            check=False,
        )

    def test_notify_recording_persistent_stop_not_active(self):
        """Test stopping when notification is not active."""
        result = notify_recording_persistent_stop()

        assert (
            result is False
        )  # Changed: now returns False when no notification to close


class TestNotificationLifecycleIntegration:
    """
    Integration test for the full notification lifecycle.

    This test verifies the complete flow:
    - Start recording -> notification appears
    - Update recording -> notification updates
    - Stop recording -> notification closes
    """

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_full_notification_lifecycle(self, mock_run, mock_dunstify_available):
        """
        Test the complete notification lifecycle.

        Verifies:
        1. notify_recording_persistent_start() sends a notification
        2. notify_recording_persistent_update() updates it
        3. notify_recording_persistent_stop() closes it
        """
        import whisper_dictate.notifications as notifications

        # Setup: dunstify is available
        mock_dunstify_available.return_value = True

        # Reset global state
        notifications._recording_notification = None

        # Phase 1: Start recording - notification should appear
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        result_start = notify_recording_persistent_start()

        assert result_start is True, "Start notification should succeed"
        assert notifications._recording_notification is not None, (
            "Global notification should be set"
        )
        assert notifications._recording_notification._is_active is True, (
            "Notification should be active"
        )
        assert notifications._recording_notification.notification_id == "12345", (
            "Notification ID should be captured"
        )

        # Verify the start call
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-p",
                "-A",
                "stop,Stop Recording",
                "Dictation",
                "Recording in progress... press again to stop\nOr use context menu (Ctrl+Shift+.) to stop",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        # Phase 2: Update recording - notification should update
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")

        result_update = notify_recording_persistent_update("Test transcription text")

        assert result_update is True, "Update notification should succeed"
        assert notifications._recording_notification._is_active is True, (
            "Notification should still be active"
        )

        # Verify the update call
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-r",
                "12345",
                "Dictation",
                "Recording... Test transcription text",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        # Phase 3: Stop recording - notification should close
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0)

        result_stop = notify_recording_persistent_stop()

        assert result_stop is True, "Stop notification should succeed"
        assert notifications._recording_notification is None, (
            "Global notification should be cleared"
        )

        # Verify the close call
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-C",
                "12345",
            ],
            capture_output=True,
            check=False,
        )

    @patch("whisper_dictate.notifications.is_dunstify_available")
    @patch("subprocess.run")
    def test_lifecycle_with_multiple_updates(self, mock_run, mock_dunstify_available):
        """
        Test lifecycle with multiple updates between start and stop.
        """
        import whisper_dictate.notifications as notifications

        mock_dunstify_available.return_value = True
        notifications._recording_notification = None

        # Start
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")
        notify_recording_persistent_start()

        # First update
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")
        result1 = notify_recording_persistent_update("First update")
        assert result1 is True

        # Second update
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")
        result2 = notify_recording_persistent_update("Second update")
        assert result2 is True

        # Third update with long text (should be truncated)
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0, stdout="12345\n", stderr="")
        long_text = "a" * 150
        result3 = notify_recording_persistent_update(long_text)
        assert result3 is True

        # Verify truncation
        expected_preview = "a" * 100 + "..."
        mock_run.assert_called_once_with(
            [
                "dunstify",
                "-u",
                "critical",
                "-t",
                "0",
                "-r",
                "12345",
                "Dictation",
                f"Recording... {expected_preview}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        # Stop
        mock_run.reset_mock()
        mock_run.return_value = Mock(returncode=0)
        result_stop = notify_recording_persistent_stop()
        assert result_stop is True

    @patch("whisper_dictate.notifications.is_dunstify_available")
    def test_lifecycle_dunstify_not_available(self, mock_dunstify_available):
        """
        Test that lifecycle handles dunstify not being available gracefully.
        """
        import whisper_dictate.notifications as notifications

        mock_dunstify_available.return_value = False
        notifications._recording_notification = None

        # Start should fail gracefully
        result_start = notify_recording_persistent_start()
        assert result_start is False

        # Update should fail gracefully
        result_update = notify_recording_persistent_update("Test")
        assert result_update is False

        # Stop should fail gracefully when no notification to close
        result_stop = notify_recording_persistent_stop()
        assert (
            result_stop is False
        )  # Changed: now returns False when no notification exists
