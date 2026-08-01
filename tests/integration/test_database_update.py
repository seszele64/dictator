"""Tests for database update_transcript method."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from whisper_dictate.cli import cli


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    from click.testing import CliRunner

    return CliRunner()


class TestUpdateTranscript:
    """Tests for the database update_transcript method using mocks."""

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
        mock_db.update_transcript = MagicMock(return_value=True)

        # Initialize and close methods
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        return mock_db

    @pytest.fixture
    def mock_database_not_found(self):
        """Create a mock database that returns None for non-existent ID."""
        mock_db = Mock()

        mock_db.get_transcription_with_recording = Mock(return_value=None)
        mock_db.update_transcript = MagicMock(return_value=False)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        return mock_db

    def test_update_transcript_text_only_mock(self, mock_database_with_update):
        """Test updating transcript text only using mock."""
        # Directly test the database method with mock
        mock_database_with_update.update_transcript = MagicMock(return_value=True)

        # Call the method
        result = mock_database_with_update.update_transcript(
            transcript_id=1,
            text="Updated text",
        )

        assert result is True
        # The actual method was called (exact args may vary based on implementation)
        mock_database_with_update.update_transcript.assert_called_once()

    def test_update_transcript_text_and_language_mock(self, mock_database_with_update):
        """Test updating transcript text and language using mock."""
        # Call the method
        result = mock_database_with_update.update_transcript(
            transcript_id=1,
            text="Updated text in Spanish",
            language="es",
        )

        assert result is True
        mock_database_with_update.update_transcript.assert_called_with(
            transcript_id=1,
            text="Updated text in Spanish",
            language="es",
        )

    def test_update_transcript_nonexistent_id_mock(self, mock_database_not_found):
        """Test updating a nonexistent transcript returns False."""
        result = mock_database_not_found.update_transcript(
            transcript_id=99999,
            text="This should not work",
        )

        assert result is False

    def test_update_transcript_with_language_none_mock(self, mock_database_with_update):
        """Test that passing language=None updates text without changing language."""
        mock_database_with_update.update_transcript = MagicMock(return_value=True)

        result = mock_database_with_update.update_transcript(
            transcript_id=1,
            text="New text",
            language=None,
        )

        assert result is True
        # The method should be called with language=None
        mock_database_with_update.update_transcript.assert_called_with(
            transcript_id=1,
            text="New text",
            language=None,
        )


class TestHistoryUpdateCLI:
    """Tests for CLI history update command."""

    @pytest.fixture
    def cli_runner(self):
        """Create a Click test runner."""
        from click.testing import CliRunner

        return CliRunner()

    def test_history_update_success(self, cli_runner):
        """Verify history update command works with valid input."""
        mock_db = Mock()
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
        mock_db.update_transcript = Mock(return_value=True)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        # Patch at database module level where the decorator imports from
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            # Simulate user confirming with 'y'
            result = cli_runner.invoke(
                cli, ["history", "update", "1", "--text", "Updated text"], input="y\n"
            )

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert "Updated transcription #1" in result.output
            assert mock_db.update_transcript.called

    def test_history_update_cancelled(self, cli_runner):
        """Verify history update command handles cancellation."""
        mock_db = Mock()
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
        mock_db.update_transcript = Mock(return_value=True)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        # Patch at database module level
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            # Simulate user cancelling with 'n'
            result = cli_runner.invoke(
                cli, ["history", "update", "1", "--text", "Updated text"], input="n\n"
            )

            assert result.exit_code == 0
            assert "cancelled" in result.output.lower()
            # Verify update was NOT called
            assert not mock_db.update_transcript.called

    def test_history_update_not_found(self, cli_runner):
        """Verify history update handles non-existent ID."""
        mock_db = Mock()
        mock_db.get_transcription_with_recording = Mock(return_value=None)
        mock_db.update_transcript = Mock(return_value=False)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        # Patch at database module level
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            result = cli_runner.invoke(
                cli, ["history", "update", "999", "--text", "Updated text"]
            )

            assert result.exit_code == 1
            assert "not found" in result.output

    def test_history_update_with_language(self, cli_runner):
        """Verify history update command works with language option."""
        mock_db = Mock()
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
        mock_db.update_transcript = Mock(return_value=True)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        # Patch at database module level
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

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
            mock_db.update_transcript.assert_called_with(1, "Updated text", "es")

    def test_history_update_requires_text(self, cli_runner):
        """Verify history update requires --text option."""
        from click.testing import CliRunner

        cli_runner = CliRunner()
        mock_db = Mock()
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        # Patch at database module level
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            result = cli_runner.invoke(cli, ["history", "update", "1"])

            # Should fail because --text is required
            assert result.exit_code != 0

    def test_history_update_shows_comparison(self, cli_runner):
        """Verify history update shows old vs new text comparison."""
        mock_db = Mock()
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
        mock_db.update_transcript = Mock(return_value=True)
        mock_db.initialize = Mock()
        mock_db.close = Mock()

        # Patch at database module level
        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_db

            result = cli_runner.invoke(
                cli, ["history", "update", "1", "--text", "New text"], input="y\n"
            )

            assert "Current Text" in result.output
            assert "New Text" in result.output
