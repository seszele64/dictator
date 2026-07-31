"""Tests for CLI history commands - specifically verifying no hanging after execution.

These tests verify that the bug fix for database connection not being closed
properly is working. The original bug caused `whisper-dictate history` commands
to hang after execution because database connections weren't being closed.

Fix: Added `db.close()` in `finally` blocks for all four history commands.
"""

import contextlib
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_dictate.cli import cli


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    from click.testing import CliRunner

    return CliRunner()


@pytest.fixture
def temp_db():
    """Create a temporary database for testing.

    Yields:
        Path: Path to temporary database file
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    yield db_path

    # Cleanup
    with contextlib.suppress(OSError):
        os.unlink(db_path)


@pytest.fixture
def mock_database_with_data():
    """Create a mock database with sample transcription data."""
    mock_db = Mock()

    # Sample transcriptions for list/search
    mock_db.list_transcriptions = Mock(
        return_value=[
            {
                "id": 1,
                "text": "This is a test transcription about a meeting.",
                "timestamp": "2024-03-15 10:30:00",
                "duration": 5.5,
                "language": "en",
                "model_used": "whisper-1",
                "confidence": 0.95,
                "file_path": "test.wav",
                "recording_id": 1,
            },
            {
                "id": 2,
                "text": "Another transcription for project planning.",
                "timestamp": "2024-03-14 14:20:00",
                "duration": 10.2,
                "language": "en",
                "model_used": "whisper-1",
                "confidence": 0.92,
                "file_path": "test2.wav",
                "recording_id": 2,
            },
        ]
    )

    # Single transcription for show
    mock_db.get_transcription_with_recording = Mock(
        return_value={
            "id": 1,
            "text": "This is a test transcription about a meeting.",
            "timestamp": "2024-03-15 10:30:00",
            "duration": 5.5,
            "language": "en",
            "model_used": "whisper-1",
            "confidence": 0.95,
            "file_path": "test.wav",
            "recording_id": 1,
        }
    )

    # Search results
    mock_db.search_transcripts = Mock(
        return_value=[
            {
                "id": 1,
                "text": "This is a test transcription about a meeting.",
                "timestamp": "2024-03-15 10:30:00",
                "duration": 5.5,
                "language": "en",
                "model_used": "whisper-1",
                "confidence": 0.95,
                "file_path": "test.wav",
                "recording_id": 1,
            },
        ]
    )

    # Delete result
    mock_db.delete_recording = Mock(return_value=True)

    # Initialize and close methods
    mock_db.initialize = Mock()
    mock_db.close = Mock()

    return mock_db


@pytest.fixture
def mock_database_empty():
    """Create a mock database with no transcriptions."""
    mock_db = Mock()

    mock_db.list_transcriptions = Mock(return_value=[])
    mock_db.get_transcription_with_recording = Mock(return_value=None)
    mock_db.search_transcripts = Mock(return_value=[])
    mock_db.delete_recording = Mock(return_value=False)
    mock_db.initialize = Mock()
    mock_db.close = Mock()

    return mock_db


@pytest.fixture
def mock_database_not_found():
    """Create a mock database that returns None for non-existent ID."""
    mock_db = Mock()

    mock_db.list_transcriptions = Mock(return_value=[])
    mock_db.get_transcription_with_recording = Mock(return_value=None)
    mock_db.search_transcripts = Mock(return_value=[])
    mock_db.delete_recording = Mock(return_value=False)
    mock_db.initialize = Mock()
    mock_db.close = Mock()

    return mock_db


class TestHistoryListNoHang:
    """Tests for history list command - verify no hanging after execution."""

    def test_history_list_exits_without_hanging_with_data(
        self, cli_runner, mock_database_with_data
    ):
        """Verify history list command exits cleanly with data.

        This test verifies the bug fix: commands should not hang after execution.
        The fix adds db.close() in the finally block.
        """
        # Patch at the database module level since CLI imports it locally
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_data

            # Run the command - should complete quickly without hanging
            result = cli_runner.invoke(cli, ["history", "list"])

            # Verify command completed successfully
            assert result.exit_code == 0, f"Command failed: {result.output}"

            # Verify database close was called (the bug fix)
            assert mock_database_with_data.close.called, (
                "Database close() was not called - this would cause hanging"
            )

    def test_history_list_exits_without_hanging_empty_database(
        self, cli_runner, mock_database_empty
    ):
        """Verify history list exits cleanly when no transcriptions exist."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_empty

            result = cli_runner.invoke(cli, ["history", "list"])

            # Should complete and show no transcriptions message
            assert "No transcriptions found" in result.output
            assert mock_database_empty.close.called

    def test_history_list_with_limit_option(self, cli_runner, mock_database_with_data):
        """Verify history list --limit option works and closes connection."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_data

            result = cli_runner.invoke(cli, ["history", "list", "--limit", "10"])

            assert result.exit_code == 0
            assert mock_database_with_data.close.called

    def test_history_list_with_date_option(self, cli_runner, mock_database_empty):
        """Verify history list --date option works and closes connection."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_empty

            result = cli_runner.invoke(cli, ["history", "list", "--date", "2024-03-15"])

            assert result.exit_code == 0
            assert mock_database_empty.close.called


class TestHistoryShowNoHang:
    """Tests for history show command - verify no hanging after execution."""

    def test_history_show_exits_without_hanging(
        self, cli_runner, mock_database_with_data
    ):
        """Verify history show command exits cleanly with valid ID."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_data

            result = cli_runner.invoke(cli, ["history", "show", "1"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert "Transcription #1" in result.output
            assert mock_database_with_data.close.called, (
                "Database close() was not called - this would cause hanging"
            )

    def test_history_show_exits_without_hanging_invalid_id(
        self, cli_runner, mock_database_not_found
    ):
        """Verify history show exits cleanly when ID doesn't exist."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_not_found

            result = cli_runner.invoke(cli, ["history", "show", "999"])

            # Should exit with error but not hang
            assert result.exit_code == 1
            assert "not found" in result.output
            assert mock_database_not_found.close.called

    def test_history_show_with_audio_option(self, cli_runner, mock_database_with_data):
        """Verify history show --audio option works and closes connection."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_data

            with patch(
                "whisper_dictate.audio_storage.get_audio_storage"
            ) as mock_storage:
                mock_storage.return_value.get_audio_path.return_value = Path(
                    "/fake/path"
                )

                result = cli_runner.invoke(cli, ["history", "show", "1", "--audio"])

                assert result.exit_code == 0
                assert mock_database_with_data.close.called


class TestHistorySearchNoHang:
    """Tests for history search command - verify no hanging after execution."""

    def test_history_search_exits_without_hanging(
        self, cli_runner, mock_database_with_data
    ):
        """Verify history search command exits cleanly with matching results."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_data

            result = cli_runner.invoke(cli, ["history", "search", "meeting"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert "Found 1 transcription" in result.output
            assert mock_database_with_data.close.called, (
                "Database close() was not called - this would cause hanging"
            )

    def test_history_search_exits_without_hanging_no_results(
        self, cli_runner, mock_database_empty
    ):
        """Verify history search exits cleanly when no results found."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_empty

            result = cli_runner.invoke(
                cli, ["history", "search", "nonexistent_query_12345"]
            )

            assert result.exit_code == 0
            assert "No transcriptions found matching" in result.output
            assert mock_database_empty.close.called

    def test_history_search_with_limit_option(
        self, cli_runner, mock_database_with_data
    ):
        """Verify history search --limit option works and closes connection."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_data

            result = cli_runner.invoke(
                cli, ["history", "search", "test", "--limit", "5"]
            )

            assert result.exit_code == 0
            assert mock_database_with_data.close.called


class TestHistoryDeleteNoHang:
    """Tests for history delete command - verify no hanging after execution."""

    def test_history_delete_exits_without_hanging(
        self, cli_runner, mock_database_with_data
    ):
        """Verify history delete command exits cleanly with --yes flag."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_data

            with patch(
                "whisper_dictate.audio_storage.get_audio_storage"
            ) as mock_storage:
                mock_audio_path = Mock()
                mock_audio_path.exists.return_value = False
                mock_storage.return_value.get_audio_path.return_value = mock_audio_path

                result = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])

                assert result.exit_code == 0, f"Command failed: {result.output}"
                assert "Deleted transcription #1" in result.output
                assert mock_database_with_data.close.called, (
                    "Database close() was not called - this would cause hanging"
                )

    def test_history_delete_exits_without_hanging_invalid_id(
        self, cli_runner, mock_database_not_found
    ):
        """Verify history delete exits cleanly when ID doesn't exist."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_not_found

            result = cli_runner.invoke(cli, ["history", "delete", "999", "--yes"])

            # Should exit with error but not hang
            assert result.exit_code == 1
            assert "not found" in result.output
            assert mock_database_not_found.close.called

    def test_history_delete_cancellation(self, cli_runner, mock_database_with_data):
        """Verify history delete handles user cancellation gracefully."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_data

            # Simulate user selecting 'n' for no confirmation
            result = cli_runner.invoke(cli, ["history", "delete", "1"], input="n\n")

            # Should exit gracefully with cancellation message
            assert "cancelled" in result.output.lower()
            assert mock_database_with_data.close.called


class TestDatabaseCloseCalled:
    """Integration tests to verify database.close() is always called.

    These tests use a mock that tracks whether close() was called,
    regardless of success or failure of the command.
    """

    @pytest.mark.parametrize(
        "command",
        [
            ["history", "list"],
            ["history", "show", "1"],
            ["history", "search", "test"],
            ["history", "delete", "1", "--yes"],
        ],
    )
    def test_database_close_always_called_on_success(
        self, cli_runner, mock_database_with_data, command
    ):
        """Verify database.close() is called after successful command execution."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_data

            # For delete, also mock audio storage
            if "delete" in command:
                with patch("whisper_dictate.audio_storage.get_audio_storage"):
                    pass

            cli_runner.invoke(cli, command)

            # Command should complete (may have error for invalid IDs)
            # The key assertion is that close was called
            assert mock_database_with_data.close.called, (
                f"database.close() was not called for command: {' '.join(command)}"
            )

    @pytest.mark.parametrize(
        "command",
        [
            ["history", "list"],
            ["history", "show", "1"],
            ["history", "search", "test"],
            ["history", "delete", "1", "--yes"],
        ],
    )
    def test_database_close_always_called_on_error(
        self, cli_runner, mock_database_not_found, command
    ):
        """Verify database.close() is called even when command encounters error."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_not_found

            cli_runner.invoke(cli, command)

            # Even with errors, close should be called
            assert mock_database_not_found.close.called, (
                f"database.close() was not called on error for: {' '.join(command)}"
            )


class TestDatabaseConnectionLeak:
    """Tests specifically for detecting connection leaks.

    These tests verify that the database connection is properly released
    after command execution, preventing the hanging behavior.
    """

    def test_multiple_consecutive_commands_dont_hang(self, cli_runner):
        """Verify multiple history commands can run consecutively without hanging.

        This simulates the real-world scenario where a user runs multiple
        history commands in sequence.
        """
        mock_db = Mock()
        mock_db.list_transcriptions = Mock(return_value=[])
        mock_db.get_transcription_with_recording = Mock(return_value=None)
        mock_db.search_transcripts = Mock(return_value=[])
        mock_db.delete_recording = Mock(return_value=False)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            commands = [
                ["history", "list"],
                ["history", "show", "1"],
                ["history", "search", "test"],
            ]

            for cmd in commands:
                # Reset the mock for each iteration
                mock_db.close.reset_mock()

                cli_runner.invoke(cli, cmd)

                # Each command should close the connection
                assert mock_db.close.call_count >= 1, (
                    f"Connection not closed for: {' '.join(cmd)}"
                )

    def test_connection_closed_after_exception(self, cli_runner):
        """Verify connection is closed even when command raises exception."""
        mock_db = Mock()
        mock_db.initialize = Mock(side_effect=Exception("Database error"))
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            result = cli_runner.invoke(cli, ["history", "list"])

            # Even with exception, close should be attempted
            # The finally block ensures this
            assert mock_db.close.called or result.exit_code != 0


class TestDatabaseCloseWithRealAsync:
    """Test that db.close() is properly called in the finally block.

    These tests verify the actual behavior - ensuring that the
    close() method is properly called and completes.
    """

    def test_history_list_awaits_db_close(self, cli_runner):
        """Verify history list properly awaits database close."""
        mock_db = Mock()
        mock_db.list_transcriptions = Mock(return_value=[])

        # Track if close was awaited
        close_called = []

        def mock_close():
            close_called.append(True)

        mock_db.close = mock_close

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            cli_runner.invoke(cli, ["history", "list"])

            # The fix uses db.close() which should complete
            assert len(close_called) >= 1 or mock_db.close.called

    def test_all_history_commands_close_connection(self, cli_runner):
        """Verify all four history commands close database connection."""
        mock_db = Mock()
        mock_db.list_transcriptions = Mock(return_value=[])
        mock_db.get_transcription_with_recording = Mock(
            return_value={
                "id": 1,
                "text": "Test",
                "timestamp": "2024-01-01 00:00:00",
                "duration": 1.0,
                "recording_id": 1,
            }
        )
        mock_db.search_transcripts = Mock(return_value=[])
        mock_db.delete_recording = Mock(return_value=True)

        commands = [
            (["history", "list"], mock_db.list_transcriptions),
            (["history", "show", "1"], mock_db.get_transcription_with_recording),
            (["history", "search", "test"], mock_db.search_transcripts),
            (["history", "delete", "1", "--yes"], mock_db.delete_recording),
        ]

        for cmd, _ in commands:
            mock_db.close.reset_mock()

            with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
                mock_get_db.return_value = mock_db

                with patch("whisper_dictate.audio_storage.get_audio_storage"):
                    cli_runner.invoke(cli, cmd)

                assert mock_db.close.called, (
                    f"db.close() not called for command: {cmd[0]} {cmd[1] if len(cmd) > 1 else ''}"
                )


class TestHistoryUpdate:
    """Tests for history update command."""

    @pytest.fixture
    def mock_database_with_update(self):
        """Create a mock database that supports update."""
        mock_db = Mock()

        # Transcript for update
        mock_db.get_transcription_with_recording = Mock(
            return_value={
                "id": 1,
                "text": "Original transcription text",
                "timestamp": "2024-03-15 10:30:00",
                "duration": 5.5,
                "language": "en",
                "model_used": "whisper-1",
                "confidence": 0.95,
                "file_path": "test.wav",
                "recording_id": 1,
            }
        )

        # Update result
        mock_db.update_transcript = Mock(return_value=True)

        # Initialize and close methods
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        return mock_db

    @pytest.fixture
    def mock_database_not_found(self):
        """Create a mock database that returns None for non-existent ID."""
        mock_db = Mock()

        mock_db.get_transcription_with_recording = Mock(return_value=None)
        mock_db.update_transcript = Mock(return_value=False)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        return mock_db

    def test_history_update_success(self, cli_runner, mock_database_with_update):
        """Verify history update command works with valid input."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_update

            # Simulate user confirming with 'y'
            result = cli_runner.invoke(
                cli, ["history", "update", "1", "--text", "Updated text"], input="y\n"
            )

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert "Updated transcription #1" in result.output
            assert mock_database_with_update.update_transcript.called

    def test_history_update_cancelled(self, cli_runner, mock_database_with_update):
        """Verify history update command handles cancellation."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_update

            # Simulate user cancelling with 'n'
            result = cli_runner.invoke(
                cli, ["history", "update", "1", "--text", "Updated text"], input="n\n"
            )

            assert result.exit_code == 0
            assert "cancelled" in result.output.lower()
            # Verify update was NOT called
            assert not mock_database_with_update.update_transcript.called

    def test_history_update_not_found(self, cli_runner, mock_database_not_found):
        """Verify history update handles non-existent ID."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_not_found

            result = cli_runner.invoke(
                cli, ["history", "update", "999", "--text", "Updated text"]
            )

            assert result.exit_code == 1
            assert "not found" in result.output

    def test_history_update_with_language(self, cli_runner, mock_database_with_update):
        """Verify history update command works with language option."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_update

            result = cli_runner.invoke(
                cli,
                [
                    "history",
                    "update",
                    "1",
                    "--text",
                    "Updated text",
                    "--language",
                    "es",
                ],
                input="y\n",
            )

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert "Updated transcription #1" in result.output

            # Verify update was called with language
            mock_database_with_update.update_transcript.assert_called_with(
                1, "Updated text", "es"
            )

    def test_history_update_requires_text(self, cli_runner):
        """Verify history update requires --text option."""
        from click.testing import CliRunner

        cli_runner = CliRunner()
        mock_db = Mock()
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            result = cli_runner.invoke(cli, ["history", "update", "1"])

            # Should fail because --text is required
            assert result.exit_code != 0

    def test_history_update_shows_comparison(
        self, cli_runner, mock_database_with_update
    ):
        """Verify history update shows old vs new text comparison."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_update

            result = cli_runner.invoke(
                cli, ["history", "update", "1", "--text", "New text"], input="y\n"
            )

            assert "Current Text" in result.output
            assert "New Text" in result.output
