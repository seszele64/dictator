"""Tests verifying that CLI commands properly close the database connection.

This suite merges coverage previously split across ``test_history.py`` and
``test_cli_database_lifecycle.py``. All commands that open a database via the
``with_database`` decorator must call ``db.close()`` after execution - whether
they succeed, fail, or raise an exception - to prevent connection leaks and
hanging behavior.
"""

import contextlib
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from whisper_dictate.cli import cli


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def mock_db_with_data():
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

    # Delete and update results
    mock_db.delete_recording = Mock(return_value=True)
    mock_db.update_transcript = Mock(return_value=True)

    # Initialize and close methods
    mock_db.initialize = Mock()
    mock_db.close = Mock()

    return mock_db


@pytest.fixture
def mock_db_empty():
    """Create a mock database with no transcriptions."""
    mock_db = Mock()

    mock_db.list_transcriptions = Mock(return_value=[])
    mock_db.get_transcription_with_recording = Mock(return_value=None)
    mock_db.search_transcripts = Mock(return_value=[])
    mock_db.delete_recording = Mock(return_value=False)
    mock_db.update_transcript = Mock(return_value=False)
    mock_db.initialize = Mock()
    mock_db.close = Mock()

    return mock_db


@pytest.fixture
def mock_db_with_logs():
    """Create a mock database with sample log data."""
    mock_db = Mock()

    # Sample logs for list/export
    mock_db.query_logs = Mock(
        return_value=[
            {
                "id": 1,
                "timestamp": "2024-03-15 10:30:00",
                "level": "INFO",
                "source": "whisper_dictate.audio",
                "message": "Recording started",
                "metadata_json": None,
            },
            {
                "id": 2,
                "timestamp": "2024-03-15 10:30:05",
                "level": "WARNING",
                "source": "whisper_dictate.audio",
                "message": "High noise level detected",
                "metadata_json": None,
            },
            {
                "id": 3,
                "timestamp": "2024-03-15 10:31:00",
                "level": "ERROR",
                "source": "whisper_dictate.database",
                "message": "Connection timeout",
                "metadata_json": '{"retry_count": 3}',
            },
        ]
    )

    # Cleanup result
    mock_db.cleanup_old_logs = Mock(return_value=2)

    # Initialize and close methods
    mock_db.initialize = Mock()
    mock_db.close = Mock()

    return mock_db


@pytest.fixture
def mock_db_empty_logs():
    """Create a mock database with no logs."""
    mock_db = Mock()
    mock_db.query_logs = Mock(return_value=[])
    mock_db.cleanup_old_logs = Mock(return_value=0)
    mock_db.initialize = Mock()
    mock_db.close = Mock()
    return mock_db


class TestHistoryListClose:
    """Tests for history list command - verify db.close() is called."""

    def test_history_list_exits_without_hanging_with_data(self, cli_runner, mock_db_with_data):
        """Verify history list command exits cleanly with data.

        This test verifies the bug fix: commands should not hang after execution.
        The fix adds db.close() in the finally block.
        """
        # Patch at the database module level since CLI imports it locally
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_data

            # Run the command - should complete quickly without hanging
            result = cli_runner.invoke(cli, ["history", "list"])

            # Verify command completed successfully
            assert result.exit_code == 0, f"Command failed: {result.output}"

            # Verify database close was called (the bug fix)
            assert mock_db_with_data.close.called, "Database close() was not called - this would cause hanging"

    def test_history_list_exits_without_hanging_empty_database(self, cli_runner, mock_db_empty):
        """Verify history list exits cleanly when no transcriptions exist."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_empty

            result = cli_runner.invoke(cli, ["history", "list"])

            # Should complete and show no transcriptions message
            assert "No transcriptions found" in result.output
            assert mock_db_empty.close.called

    def test_history_list_with_limit_option(self, cli_runner, mock_db_with_data):
        """Verify history list --limit option works and closes connection."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_data

            result = cli_runner.invoke(cli, ["history", "list", "--limit", "10"])

            assert result.exit_code == 0
            assert mock_db_with_data.close.called

    def test_history_list_with_date_option(self, cli_runner, mock_db_empty):
        """Verify history list --date option works and closes connection."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_empty

            result = cli_runner.invoke(cli, ["history", "list", "--date", "2024-03-15"])

            assert result.exit_code == 0
            assert mock_db_empty.close.called


class TestHistoryShowClose:
    """Tests for history show command - verify db.close() is called."""

    def test_history_show_exits_without_hanging(self, cli_runner, mock_db_with_data):
        """Verify history show command exits cleanly with valid ID."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_data

            result = cli_runner.invoke(cli, ["history", "show", "1"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert "Transcription #1" in result.output
            assert mock_db_with_data.close.called, "Database close() was not called - this would cause hanging"

    def test_history_show_exits_without_hanging_invalid_id(self, cli_runner, mock_db_empty):
        """Verify history show exits cleanly when ID doesn't exist."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_empty

            result = cli_runner.invoke(cli, ["history", "show", "999"])

            # Should exit with error but not hang
            assert result.exit_code == 1
            assert "not found" in result.output
            assert mock_db_empty.close.called

    def test_history_show_with_audio_option(self, cli_runner, mock_db_with_data):
        """Verify history show --audio option works and closes connection."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_data

            with patch("whisper_dictate.audio_storage.AudioStorage") as mock_storage:
                mock_storage.return_value.get_audio_path.return_value = Path("/fake/path")

                result = cli_runner.invoke(cli, ["history", "show", "1", "--audio"])

                assert result.exit_code == 0
                assert mock_db_with_data.close.called


class TestHistorySearchClose:
    """Tests for history search command - verify db.close() is called."""

    def test_history_search_exits_without_hanging(self, cli_runner, mock_db_with_data):
        """Verify history search command exits cleanly with matching results."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_data

            result = cli_runner.invoke(cli, ["history", "search", "meeting"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert "Found 1 transcription" in result.output
            assert mock_db_with_data.close.called, "Database close() was not called - this would cause hanging"

    def test_history_search_exits_without_hanging_no_results(self, cli_runner, mock_db_empty):
        """Verify history search exits cleanly when no results found."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_empty

            result = cli_runner.invoke(cli, ["history", "search", "nonexistent_query_12345"])

            assert result.exit_code == 0
            assert "No transcriptions found matching" in result.output
            assert mock_db_empty.close.called

    def test_history_search_with_limit_option(self, cli_runner, mock_db_with_data):
        """Verify history search --limit option works and closes connection."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_data

            result = cli_runner.invoke(cli, ["history", "search", "test", "--limit", "5"])

            assert result.exit_code == 0
            assert mock_db_with_data.close.called


class TestHistoryDeleteClose:
    """Tests for history delete command - verify db.close() is called."""

    def test_history_delete_exits_without_hanging(self, cli_runner, mock_db_with_data):
        """Verify history delete command exits cleanly with --yes flag."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_data

            with patch("whisper_dictate.audio_storage.AudioStorage") as mock_storage:
                mock_audio_path = Mock()
                mock_audio_path.exists.return_value = False
                mock_storage.return_value.get_audio_path.return_value = mock_audio_path

                result = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])

                assert result.exit_code == 0, f"Command failed: {result.output}"
                assert "Deleted transcription #1" in result.output
                assert mock_db_with_data.close.called, "Database close() was not called - this would cause hanging"

    def test_history_delete_exits_without_hanging_invalid_id(self, cli_runner, mock_db_empty):
        """Verify history delete exits cleanly when ID doesn't exist."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_empty

            result = cli_runner.invoke(cli, ["history", "delete", "999", "--yes"])

            # Should exit with error but not hang
            assert result.exit_code == 1
            assert "not found" in result.output
            assert mock_db_empty.close.called

    def test_history_delete_cancellation(self, cli_runner, mock_db_with_data):
        """Verify history delete handles user cancellation gracefully."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_data

            # Simulate user selecting 'n' for no confirmation
            result = cli_runner.invoke(cli, ["history", "delete", "1"], input="n\n")

            # Should exit gracefully with cancellation message
            assert "cancelled" in result.output.lower()
            assert mock_db_with_data.close.called


class TestHistoryUpdate:
    """Tests for history update command."""

    @pytest.fixture
    def mock_db_with_update(self):
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
    def mock_db_update_not_found(self):
        """Create a mock database that returns None for non-existent ID."""
        mock_db = Mock()

        mock_db.get_transcription_with_recording = Mock(return_value=None)
        mock_db.update_transcript = Mock(return_value=False)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        return mock_db

    def test_history_update_success(self, cli_runner, mock_db_with_update):
        """Verify history update command works with valid input."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_update

            # Simulate user confirming with 'y'
            result = cli_runner.invoke(cli, ["history", "update", "1", "--text", "Updated text"], input="y\n")

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert "Updated transcription #1" in result.output
            assert mock_db_with_update.update_transcript.called

    def test_history_update_cancelled(self, cli_runner, mock_db_with_update):
        """Verify history update command handles cancellation."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_update

            # Simulate user cancelling with 'n'
            result = cli_runner.invoke(cli, ["history", "update", "1", "--text", "Updated text"], input="n\n")

            assert result.exit_code == 0
            assert "cancelled" in result.output.lower()
            # Verify update was NOT called
            assert not mock_db_with_update.update_transcript.called

    def test_history_update_not_found(self, cli_runner, mock_db_update_not_found):
        """Verify history update handles non-existent ID."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_update_not_found

            result = cli_runner.invoke(cli, ["history", "update", "999", "--text", "Updated text"])

            assert result.exit_code == 1
            assert "not found" in result.output

    def test_history_update_with_language(self, cli_runner, mock_db_with_update):
        """Verify history update command works with language option."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_update

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
            mock_db_with_update.update_transcript.assert_called_with(1, "Updated text", "es")

    def test_history_update_requires_text(self, cli_runner):
        """Verify history update requires --text option."""
        mock_db = Mock()
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

            result = cli_runner.invoke(cli, ["history", "update", "1"])

            # Should fail because --text is required
            assert result.exit_code != 0

    def test_history_update_shows_comparison(self, cli_runner, mock_db_with_update):
        """Verify history update shows old vs new text comparison."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_update

            result = cli_runner.invoke(cli, ["history", "update", "1", "--text", "New text"], input="y\n")

            assert "Current Text" in result.output
            assert "New Text" in result.output


class TestLogsCommandsClose:
    """Verify all logs subcommands properly close database connections."""

    def test_logs_list_calls_db_close(self, cli_runner, mock_db_with_logs):
        """Verify logs list command calls database close()."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_logs

            result = cli_runner.invoke(cli, ["logs", "list"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert mock_db_with_logs.close.called, "Database close() was not called - this would cause connection leak"

    def test_logs_list_with_filters_calls_db_close(self, cli_runner, mock_db_with_logs):
        """Verify logs list with filter options calls database close()."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_logs

            result = cli_runner.invoke(cli, ["logs", "list", "--level", "ERROR", "--limit", "10"])

            assert result.exit_code == 0
            assert mock_db_with_logs.close.called

    def test_logs_list_no_results_calls_db_close(self, cli_runner, mock_db_empty_logs):
        """Verify logs list with no results calls database close()."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_empty_logs

            result = cli_runner.invoke(cli, ["logs", "list"])

            assert result.exit_code == 0
            assert mock_db_empty_logs.close.called

    def test_logs_export_calls_db_close(self, cli_runner, mock_db_with_logs):
        """Verify logs export command calls database close()."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_logs

            # Use a temp file for export
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
                export_file = f.name

            try:
                result = cli_runner.invoke(cli, ["logs", "export", export_file], input="y\n")

                assert result.exit_code == 0, f"Command failed: {result.output}"
                assert mock_db_with_logs.close.called, (
                    "Database close() was not called - this would cause connection leak"
                )
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(export_file)

    def test_logs_export_json_format_calls_db_close(self, cli_runner, mock_db_with_logs):
        """Verify logs export with JSON format calls database close()."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_logs

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                export_file = f.name

            try:
                result = cli_runner.invoke(
                    cli,
                    ["logs", "export", export_file, "--format", "json"],
                    input="y\n",
                )

                assert result.exit_code == 0
                assert mock_db_with_logs.close.called
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(export_file)

    def test_logs_cleanup_calls_db_close(self, cli_runner, mock_db_with_logs):
        """Verify logs cleanup command calls database close()."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_logs

            result = cli_runner.invoke(cli, ["logs", "cleanup", "--days", "7"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert mock_db_with_logs.close.called, "Database close() was not called - this would cause connection leak"

    def test_logs_cleanup_default_days_calls_db_close(self, cli_runner, mock_db_with_logs):
        """Verify logs cleanup with default days calls database close()."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db_with_logs

            result = cli_runner.invoke(cli, ["logs", "cleanup"])

            assert result.exit_code == 0
            assert mock_db_with_logs.close.called


class TestMigrateCommand:
    """Verify migrate command works without database (for completeness)."""

    def test_migrate_status_no_database(self, cli_runner):
        """Verify migrate --status doesn't require database."""
        # This test verifies the migrate command works without database
        # by mocking the migration functions
        with patch("whisper_dictate.migration.check_migration_status") as mock_status:
            mock_status.return_value = {
                "legacy_files": {
                    "state_file": False,
                    "pid_file": False,
                    "audio_file": False,
                },
                "migration_completed": True,
                "migration_needed": False,
            }

            result = cli_runner.invoke(cli, ["migrate", "--status"])

            assert result.exit_code == 0
            assert "Migration Status" in result.output

    def test_migrate_runs_without_database(self, cli_runner):
        """Verify migrate command works without database."""
        with patch("whisper_dictate.migration.run_migration") as mock_migrate:
            mock_migrate.return_value = {
                "success": True,
                "skipped": False,
                "migrated_files": {},
                "message": "Migration completed",
            }

            result = cli_runner.invoke(cli, ["migrate"])

            # Should succeed (or skip if no files to migrate)
            assert result.exit_code in [0, 1]


class TestDatabaseErrorHandling:
    """Verify database close is called even when errors occur."""

    def test_connection_closed_after_exception(self, cli_runner):
        """Verify connection is closed even when command raises exception."""
        mock_db = Mock()
        mock_db.initialize = Mock(side_effect=Exception("Database error"))
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

            result = cli_runner.invoke(cli, ["history", "list"])

            # S1: initialization happens INSIDE the try/finally, so an
            # initialize failure must close the database unconditionally -
            # the old `close.called or exit_code != 0` escape hatch is gone.
            assert mock_db.close.called
            assert result.exit_code != 0

    def test_logs_list_db_error_still_closes(self, cli_runner):
        """Verify logs list closes database even when error occurs."""
        mock_db = Mock()
        mock_db.initialize = Mock()
        mock_db.query_logs = Mock(side_effect=Exception("Database error"))
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

            result = cli_runner.invoke(cli, ["logs", "list"])

            # Should fail but close should still be called
            assert result.exit_code != 0
            assert mock_db.close.called

    def test_history_list_db_error_still_closes(self, cli_runner):
        """Verify history list closes database even when error occurs."""
        mock_db = Mock()
        mock_db.initialize = Mock()
        mock_db.list_transcriptions = Mock(side_effect=Exception("Database error"))
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

            result = cli_runner.invoke(cli, ["history", "list"])

            # Should fail but close should still be called
            assert result.exit_code != 0
            assert mock_db.close.called


class TestConnectionLeak:
    """Verify multiple consecutive commands don't leak connections."""

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

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

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
                assert mock_db.close.call_count >= 1, f"Connection not closed for: {' '.join(cmd)}"

    def test_consecutive_logs_commands(self, cli_runner):
        """Verify multiple logs commands can run without connection issues."""
        mock_db = Mock()
        mock_db.query_logs = Mock(return_value=[])
        mock_db.cleanup_old_logs = Mock(return_value=0)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

            # Run multiple commands consecutively
            commands = [
                ["logs", "list"],
                ["logs", "cleanup"],
                ["logs", "list", "--level", "ERROR"],
            ]

            for cmd in commands:
                mock_db.close.reset_mock()
                cli_runner.invoke(cli, cmd)
                assert mock_db.close.call_count >= 1, f"Connection not closed for: {' '.join(cmd)}"

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
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        commands = [
            (["history", "list"], mock_db.list_transcriptions),
            (["history", "show", "1"], mock_db.get_transcription_with_recording),
            (["history", "search", "test"], mock_db.search_transcripts),
            (["history", "delete", "1", "--yes"], mock_db.delete_recording),
        ]

        for cmd, _ in commands:
            mock_db.close.reset_mock()

            with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
                mock_database_cls.return_value = mock_db

                with patch("whisper_dictate.audio_storage.AudioStorage"):
                    cli_runner.invoke(cli, cmd)

                assert mock_db.close.called, (
                    f"db.close() not called for command: {cmd[0]} {cmd[1] if len(cmd) > 1 else ''}"
                )


class TestHistoryUpdateStorageSafety:
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
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_database_with_update

            # Simulate user confirming with 'y'
            result = cli_runner.invoke(cli, ["history", "update", "1", "--text", "Updated text"], input="y\n")

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert "Updated transcription #1" in result.output
            assert mock_database_with_update.update_transcript.called

    def test_history_update_cancelled(self, cli_runner, mock_database_with_update):
        """Verify history update command handles cancellation."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_database_with_update

            # Simulate user cancelling with 'n'
            result = cli_runner.invoke(cli, ["history", "update", "1", "--text", "Updated text"], input="n\n")

            assert result.exit_code == 0
            assert "cancelled" in result.output.lower()
            # Verify update was NOT called
            assert not mock_database_with_update.update_transcript.called

    def test_history_update_not_found(self, cli_runner, mock_database_not_found):
        """Verify history update handles non-existent ID."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_database_not_found

            result = cli_runner.invoke(cli, ["history", "update", "999", "--text", "Updated text"])

            assert result.exit_code == 1
            assert "not found" in result.output

    def test_history_update_with_language(self, cli_runner, mock_database_with_update):
        """Verify history update command works with language option."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_database_with_update

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
            mock_database_with_update.update_transcript.assert_called_with(1, "Updated text", "es")

    def test_history_update_requires_text(self, cli_runner):
        """Verify history update requires --text option."""
        from click.testing import CliRunner

        cli_runner = CliRunner()
        mock_db = Mock()
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

            result = cli_runner.invoke(cli, ["history", "update", "1"])

            # Should fail because --text is required
            assert result.exit_code != 0

    def test_history_update_shows_comparison(self, cli_runner, mock_database_with_update):
        """Verify history update shows old vs new text comparison."""
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_database_with_update

            result = cli_runner.invoke(cli, ["history", "update", "1", "--text", "New text"], input="y\n")

            assert "Current Text" in result.output
            assert "New Text" in result.output


class TestHistoryDeleteFileFirst:
    """Deletion must unlink the audio file BEFORE removing the database row.

    Regression: the row was deleted first, then the unlink crashed on
    empty/unsafe paths, leaving inconsistent state (and IsADirectoryError for
    file_path=""). Empty paths are a "no file" sentinel, unsafe paths are never
    accessed, missing files are tolerated, and real unlink errors abort the row
    deletion so disk and database stay consistent.
    """

    @pytest.fixture
    def transcription_row(self):
        return {
            "id": 1,
            "text": "Delete me",
            "timestamp": "2024-03-15 10:30:00",
            "duration": 5.5,
            "language": "en",
            "model_used": "whisper-1",
            "confidence": 0.95,
            "file_path": "2024/03/14/test.wav",
            "recording_id": 42,
        }

    def _invoke(self, cli_runner, mock_db, transcription_row):
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db
            with patch("whisper_dictate.audio_storage.AudioStorage") as mock_storage:
                result = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])
        return result, mock_storage

    def test_unlinks_file_before_deleting_row(self, cli_runner, transcription_row):
        mock_db = Mock()
        mock_db.get_transcription_with_recording = Mock(return_value=transcription_row)
        order = []

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db
            with patch("whisper_dictate.audio_storage.AudioStorage") as mock_storage:
                mock_audio_path = Mock()
                mock_audio_path.unlink.side_effect = lambda *a, **kw: order.append("unlink")
                mock_storage.return_value.get_audio_path.return_value = mock_audio_path
                mock_db.delete_recording.side_effect = lambda rid: (
                    order.append("row"),
                    True,
                )[1]

                result = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])

        assert result.exit_code == 0, result.output
        assert order == ["unlink", "row"], f"file must be unlinked first, got {order}"

    def test_empty_file_path_deletes_row_only(self, cli_runner, transcription_row):
        transcription_row["file_path"] = ""
        mock_db = Mock()
        mock_db.get_transcription_with_recording = Mock(return_value=transcription_row)
        mock_db.delete_recording = Mock(return_value=True)

        result, mock_storage = self._invoke(cli_runner, mock_db, transcription_row)

        assert result.exit_code == 0, result.output
        assert "Deleted transcription #1" in result.output
        mock_storage.return_value.get_audio_path.assert_not_called()
        mock_db.delete_recording.assert_called_once_with(42)

    def test_unsafe_path_deletes_row_only_and_warns(self, cli_runner, transcription_row):
        from whisper_dictate.audio_storage import UnsafeAudioPathError

        mock_db = Mock()
        mock_db.get_transcription_with_recording = Mock(return_value=transcription_row)
        mock_db.delete_recording = Mock(return_value=True)

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db
            with patch("whisper_dictate.audio_storage.AudioStorage") as mock_storage:
                mock_storage.return_value.get_audio_path.side_effect = UnsafeAudioPathError(
                    "escapes the recordings root"
                )
                result = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])

        assert result.exit_code == 0, result.output
        assert "escapes the recordings root" in result.output
        mock_db.delete_recording.assert_called_once_with(42)

    def test_unlink_permission_error_aborts_row_deletion(self, cli_runner, transcription_row):
        mock_db = Mock()
        mock_db.get_transcription_with_recording = Mock(return_value=transcription_row)
        mock_db.delete_recording = Mock(return_value=True)

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db
            with patch("whisper_dictate.audio_storage.AudioStorage") as mock_storage:
                mock_path = Mock()
                mock_path.unlink.side_effect = PermissionError("denied")
                mock_storage.return_value.get_audio_path.return_value = mock_path

                result = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])

        assert result.exit_code == 1
        assert "Failed to delete audio file" in result.output
        mock_db.delete_recording.assert_not_called()

    def test_missing_file_still_deletes_row(self, cli_runner, transcription_row):
        mock_db = Mock()
        mock_db.get_transcription_with_recording = Mock(return_value=transcription_row)
        mock_db.delete_recording = Mock(return_value=True)

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db
            with patch("whisper_dictate.audio_storage.AudioStorage") as mock_storage:
                mock_path = Mock()
                mock_path.unlink.side_effect = FileNotFoundError()
                mock_storage.return_value.get_audio_path.return_value = mock_path

                result = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])

        assert result.exit_code == 0, result.output
        assert mock_db.delete_recording.assert_called_once_with(42) is None

    def test_real_files_inside_and_outside_root(self, cli_runner, tmp_path):
        """End-to-end: in-root file is deleted, out-of-root file is never touched."""
        from whisper_dictate.audio_storage import AudioStorage
        from whisper_dictate.config import DatabaseConfig

        recordings_root = tmp_path / "recordings"
        inside = recordings_root / "2024/03/14"
        inside.mkdir(parents=True)
        in_root_file = inside / "rec.wav"
        in_root_file.write_bytes(b"audio")
        outside_file = tmp_path / "outside.wav"
        outside_file.write_bytes(b"do not touch")

        storage = AudioStorage(DatabaseConfig(recordings_path=recordings_root))

        mock_db = Mock()
        mock_db.get_transcription_with_recording = Mock(
            side_effect=[
                {**self.transcription_default(), "file_path": str(outside_file)},
                {
                    **self.transcription_default(),
                    "file_path": "2024/03/14/rec.wav",
                },
            ]
        )
        mock_db.delete_recording = Mock(return_value=True)

        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db
            with patch("whisper_dictate.audio_storage.AudioStorage", return_value=storage):
                # Out-of-root absolute path: row-only delete
                result1 = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])
                # In-root relative path: file deleted + row deleted
                result2 = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])

        assert result1.exit_code == 0, result1.output
        assert outside_file.exists()  # never touched
        assert result2.exit_code == 0, result2.output
        assert not in_root_file.exists()  # deleted file-first
        assert mock_db.delete_recording.call_count == 2

    @staticmethod
    def transcription_default():
        return {
            "id": 1,
            "text": "Delete me",
            "timestamp": "2024-03-15 10:30:00",
            "duration": 5.5,
            "language": "en",
            "model_used": "whisper-1",
            "confidence": 0.95,
            "recording_id": 42,
        }
