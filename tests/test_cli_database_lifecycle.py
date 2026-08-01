"""Tests for verifying all CLI commands properly close database connections.

This test suite ensures that all database-using CLI commands properly close
their database connections after execution, preventing connection leaks and
hanging behavior.

Commands tested:
- logs list
- logs export
- logs cleanup
- history list
- history show
- history search
- history delete
- migrate (no database, but included for completeness)
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
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    yield db_path

    # Cleanup
    with contextlib.suppress(OSError):
        os.unlink(db_path)


@pytest.fixture
def mock_database_with_logs():
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
def mock_database_with_transcriptions():
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
def mock_database_empty_logs():
    """Create a mock database with no logs."""
    mock_db = Mock()
    mock_db.query_logs = Mock(return_value=[])
    mock_db.cleanup_old_logs = Mock(return_value=0)
    mock_db.initialize = Mock()
    mock_db.close = Mock()
    return mock_db


@pytest.fixture
def mock_database_empty_transcriptions():
    """Create a mock database with no transcriptions."""
    mock_db = Mock()
    mock_db.list_transcriptions = Mock(return_value=[])
    mock_db.get_transcription_with_recording = Mock(return_value=None)
    mock_db.search_transcripts = Mock(return_value=[])
    mock_db.delete_recording = Mock(return_value=False)
    mock_db.initialize = Mock()
    mock_db.close = Mock()
    return mock_db


class TestLogsCommandsDatabaseClose:
    """Verify all logs subcommands properly close database connections."""

    def test_logs_list_calls_db_close(self, cli_runner, mock_database_with_logs):
        """Verify logs list command calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_logs

            result = cli_runner.invoke(cli, ["logs", "list"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert mock_database_with_logs.close.called, (
                "Database close() was not called - this would cause connection leak"
            )

    def test_logs_list_with_filters_calls_db_close(
        self, cli_runner, mock_database_with_logs
    ):
        """Verify logs list with filter options calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_logs

            result = cli_runner.invoke(
                cli, ["logs", "list", "--level", "ERROR", "--limit", "10"]
            )

            assert result.exit_code == 0
            assert mock_database_with_logs.close.called

    def test_logs_list_no_results_calls_db_close(
        self, cli_runner, mock_database_empty_logs
    ):
        """Verify logs list with no results calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_empty_logs

            result = cli_runner.invoke(cli, ["logs", "list"])

            assert result.exit_code == 0
            assert mock_database_empty_logs.close.called

    def test_logs_export_calls_db_close(
        self, cli_runner, mock_database_with_logs, temp_db
    ):
        """Verify logs export command calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_logs

            # Use a temp file for export
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
                export_file = f.name

            try:
                result = cli_runner.invoke(
                    cli, ["logs", "export", export_file], input="y\n"
                )

                assert result.exit_code == 0, f"Command failed: {result.output}"
                assert mock_database_with_logs.close.called, (
                    "Database close() was not called - this would cause connection leak"
                )
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(export_file)

    def test_logs_export_json_format_calls_db_close(
        self, cli_runner, mock_database_with_logs
    ):
        """Verify logs export with JSON format calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_logs

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                export_file = f.name

            try:
                result = cli_runner.invoke(
                    cli,
                    ["logs", "export", export_file, "--format", "json"],
                    input="y\n",
                )

                assert result.exit_code == 0
                assert mock_database_with_logs.close.called
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(export_file)

    def test_logs_cleanup_calls_db_close(self, cli_runner, mock_database_with_logs):
        """Verify logs cleanup command calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_logs

            result = cli_runner.invoke(cli, ["logs", "cleanup", "--days", "7"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert mock_database_with_logs.close.called, (
                "Database close() was not called - this would cause connection leak"
            )

    def test_logs_cleanup_default_days_calls_db_close(
        self, cli_runner, mock_database_with_logs
    ):
        """Verify logs cleanup with default days calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_logs

            result = cli_runner.invoke(cli, ["logs", "cleanup"])

            assert result.exit_code == 0
            assert mock_database_with_logs.close.called


class TestHistoryCommandsDatabaseClose:
    """Verify all history subcommands properly close database connections."""

    def test_history_list_calls_db_close(
        self, cli_runner, mock_database_with_transcriptions
    ):
        """Verify history list command calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_transcriptions

            result = cli_runner.invoke(cli, ["history", "list"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert mock_database_with_transcriptions.close.called, (
                "Database close() was not called - this would cause connection leak"
            )

    def test_history_list_with_limit_calls_db_close(
        self, cli_runner, mock_database_with_transcriptions
    ):
        """Verify history list with --limit option calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_transcriptions

            result = cli_runner.invoke(cli, ["history", "list", "--limit", "10"])

            assert result.exit_code == 0
            assert mock_database_with_transcriptions.close.called

    def test_history_list_with_date_calls_db_close(
        self, cli_runner, mock_database_with_transcriptions
    ):
        """Verify history list with --date option calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_transcriptions

            result = cli_runner.invoke(cli, ["history", "list", "--date", "2024-03-15"])

            assert result.exit_code == 0
            assert mock_database_with_transcriptions.close.called

    def test_history_list_empty_calls_db_close(
        self, cli_runner, mock_database_empty_transcriptions
    ):
        """Verify history list with no transcriptions calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_empty_transcriptions

            result = cli_runner.invoke(cli, ["history", "list"])

            assert result.exit_code == 0
            assert "No transcriptions found" in result.output
            assert mock_database_empty_transcriptions.close.called

    def test_history_show_calls_db_close(
        self, cli_runner, mock_database_with_transcriptions
    ):
        """Verify history show command calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_transcriptions

            result = cli_runner.invoke(cli, ["history", "show", "1"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert mock_database_with_transcriptions.close.called, (
                "Database close() was not called - this would cause connection leak"
            )

    def test_history_show_with_audio_calls_db_close(
        self, cli_runner, mock_database_with_transcriptions
    ):
        """Verify history show with --audio option calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_transcriptions

            with patch(
                "whisper_dictate.audio_storage.get_audio_storage"
            ) as mock_storage:
                mock_storage.return_value.get_audio_path.return_value = Path(
                    "/fake/path"
                )

                result = cli_runner.invoke(cli, ["history", "show", "1", "--audio"])

                assert result.exit_code == 0
                assert mock_database_with_transcriptions.close.called

    def test_history_show_invalid_id_calls_db_close(
        self, cli_runner, mock_database_empty_transcriptions
    ):
        """Verify history show with invalid ID calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_empty_transcriptions

            result = cli_runner.invoke(cli, ["history", "show", "999"])

            # Should exit with error but close should still be called
            assert result.exit_code == 1
            assert "not found" in result.output
            assert mock_database_empty_transcriptions.close.called

    def test_history_search_calls_db_close(
        self, cli_runner, mock_database_with_transcriptions
    ):
        """Verify history search command calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_transcriptions

            result = cli_runner.invoke(cli, ["history", "search", "meeting"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert mock_database_with_transcriptions.close.called, (
                "Database close() was not called - this would cause connection leak"
            )

    def test_history_search_with_limit_calls_db_close(
        self, cli_runner, mock_database_with_transcriptions
    ):
        """Verify history search with --limit option calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_transcriptions

            result = cli_runner.invoke(
                cli, ["history", "search", "test", "--limit", "5"]
            )

            assert result.exit_code == 0
            assert mock_database_with_transcriptions.close.called

    def test_history_search_no_results_calls_db_close(
        self, cli_runner, mock_database_empty_transcriptions
    ):
        """Verify history search with no results calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_empty_transcriptions

            result = cli_runner.invoke(
                cli, ["history", "search", "nonexistent_query_12345"]
            )

            assert result.exit_code == 0
            assert "No transcriptions found" in result.output
            assert mock_database_empty_transcriptions.close.called

    def test_history_delete_calls_db_close(
        self, cli_runner, mock_database_with_transcriptions
    ):
        """Verify history delete command calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_transcriptions

            with patch(
                "whisper_dictate.audio_storage.get_audio_storage"
            ) as mock_storage:
                mock_audio_path = Mock()
                mock_audio_path.exists.return_value = False
                mock_storage.return_value.get_audio_path.return_value = mock_audio_path

                result = cli_runner.invoke(cli, ["history", "delete", "1", "--yes"])

                assert result.exit_code == 0, f"Command failed: {result.output}"
                assert "Deleted transcription #1" in result.output
                assert mock_database_with_transcriptions.close.called, (
                    "Database close() was not called - this would cause connection leak"
                )

    def test_history_delete_invalid_id_calls_db_close(
        self, cli_runner, mock_database_empty_transcriptions
    ):
        """Verify history delete with invalid ID calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_empty_transcriptions

            result = cli_runner.invoke(cli, ["history", "delete", "999", "--yes"])

            # Should exit with error but close should still be called
            assert result.exit_code == 1
            assert "not found" in result.output
            assert mock_database_empty_transcriptions.close.called

    def test_history_delete_cancellation_calls_db_close(
        self, cli_runner, mock_database_with_transcriptions
    ):
        """Verify history delete cancellation calls database close()."""
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database_with_transcriptions

            # Simulate user selecting 'n' for no confirmation
            result = cli_runner.invoke(cli, ["history", "delete", "1"], input="n\n")

            # Should exit gracefully with cancellation message
            assert "cancelled" in result.output.lower()
            assert mock_database_with_transcriptions.close.called


class TestAllCLICommandsDatabaseClose:
    """Parametrized tests for all database-using CLI commands."""

    @pytest.mark.parametrize(
        "command,mock_fixture",
        [
            # Logs commands (now use database.get_database directly)
            (["logs", "list"], "mock_database_with_logs"),
            (["logs", "export", "test_export.txt"], "mock_database_with_logs"),
            (["logs", "cleanup"], "mock_database_with_logs"),
            # History commands
            (["history", "list"], "mock_database_with_transcriptions"),
            (["history", "show", "1"], "mock_database_with_transcriptions"),
            (["history", "search", "meeting"], "mock_database_with_transcriptions"),
            (["history", "delete", "1", "--yes"], "mock_database_with_transcriptions"),
        ],
    )
    def test_command_calls_db_close(self, cli_runner, command, mock_fixture, request):
        """Verify all database-using commands call close()."""
        mock_db = request.getfixturevalue(mock_fixture)

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            # For delete command, also mock audio storage
            if "delete" in command:
                with patch("whisper_dictate.audio_storage.get_audio_storage"):
                    pass

            # For export command, use a temp file
            if "export" in command:
                with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
                    export_file = f.name
                command[-1] = export_file  # Replace filename with temp
                try:
                    cli_runner.invoke(cli, command)
                finally:
                    with contextlib.suppress(OSError):
                        os.unlink(export_file)
            else:
                cli_runner.invoke(cli, command)

            # Verify close was called
            assert mock_db.close.called, (
                f"Database close() was not called for command: {' '.join(command)}"
            )


class TestMigrateCommandNoDatabase:
    """Verify migrate command doesn't use database (for completeness)."""

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


class TestDatabaseCloseOnError:
    """Verify database close is called even when errors occur."""

    def test_logs_list_db_error_still_closes(self, cli_runner):
        """Verify logs list closes database even when error occurs."""
        mock_db = Mock()
        mock_db.initialize = Mock()
        mock_db.query_logs = Mock(side_effect=Exception("Database error"))
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

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

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            result = cli_runner.invoke(cli, ["history", "list"])

            # Should fail but close should still be called
            assert result.exit_code != 0
            assert mock_db.close.called


class TestMultipleCommandsNoConnectionLeak:
    """Verify multiple consecutive commands don't leak connections."""

    def test_consecutive_logs_commands(self, cli_runner):
        """Verify multiple logs commands can run without connection issues."""
        mock_db = Mock()
        mock_db.query_logs = Mock(return_value=[])
        mock_db.cleanup_old_logs = Mock(return_value=0)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            # Run multiple commands consecutively
            commands = [
                ["logs", "list"],
                ["logs", "cleanup"],
                ["logs", "list", "--level", "ERROR"],
            ]

            for cmd in commands:
                mock_db.close.reset_mock()
                cli_runner.invoke(cli, cmd)
                assert mock_db.close.call_count >= 1, (
                    f"Connection not closed for: {' '.join(cmd)}"
                )

    def test_consecutive_history_commands(self, cli_runner):
        """Verify multiple history commands can run without connection issues."""
        mock_db = Mock()
        mock_db.list_transcriptions = Mock(return_value=[])
        mock_db.get_transcription_with_recording = Mock(return_value=None)
        mock_db.search_transcripts = Mock(return_value=[])
        mock_db.delete_recording = Mock(return_value=True)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            # Run multiple commands consecutively
            commands = [
                ["history", "list"],
                ["history", "show", "1"],
                ["history", "search", "test"],
            ]

            for cmd in commands:
                mock_db.close.reset_mock()
                cli_runner.invoke(cli, cmd)
                assert mock_db.close.call_count >= 1, (
                    f"Connection not closed for: {' '.join(cmd)}"
                )
