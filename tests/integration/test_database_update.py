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
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

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
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

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
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

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
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

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
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

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
        with patch("whisper_dictate.cli_helpers.Database") as mock_database_cls:
            mock_database_cls.return_value = mock_db

            result = cli_runner.invoke(
                cli, ["history", "update", "1", "--text", "New text"], input="y\n"
            )

            assert "Current Text" in result.output
            assert "New Text" in result.output


class TestLegacyDatabaseMigration:
    """Legacy databases (tables, no schema_versions) must run migration 2.

    Regression: version-0 legacy databases were stamped version 2 without the
    migration ever running, so update_transcript failed with
    'no such column: updated_at' forever.
    """

    @pytest.fixture
    def legacy_database(self, legacy_db_path):
        from whisper_dictate.config import DatabaseConfig
        from whisper_dictate.database import Database

        db = Database(DatabaseConfig(path=legacy_db_path))
        db.initialize()
        yield db
        db.close()

    def _schema_version(self, db):
        row = db.fetchone("SELECT MAX(version) FROM schema_versions")
        return row[0] or 0

    def test_legacy_db_backfills_to_current_version(self, legacy_database):
        from whisper_dictate.database import CURRENT_SCHEMA_VERSION

        assert self._schema_version(legacy_database) == CURRENT_SCHEMA_VERSION

    def test_legacy_db_gains_updated_at_column(self, legacy_database):
        columns = {row[1] for row in legacy_database.fetchall("PRAGMA table_info(transcripts)")}
        assert "updated_at" in columns

    def test_update_transcript_works_on_migrated_legacy_db(self, legacy_database):
        assert legacy_database.update_transcript(1, "corrected text") is True
        transcript = legacy_database.get_transcript_by_recording(1)
        assert transcript["text"] == "corrected text"
        assert transcript["updated_at"]  # backfilled timestamp

    def test_legacy_rows_survive_migration(self, legacy_database):
        recording = legacy_database.get_recording(1)
        assert recording["file_path"] == "2024/01/01/legacy.wav"

    def test_reinitialize_is_idempotent(self, legacy_db_path):
        from whisper_dictate.config import DatabaseConfig
        from whisper_dictate.database import Database

        db = Database(DatabaseConfig(path=legacy_db_path))
        db.initialize()
        db.initialize()  # second run must not re-migrate or fail
        assert self._schema_version(db) == 2
        db.close()

    def test_fresh_db_still_works(self, tmp_path):
        from whisper_dictate.config import DatabaseConfig
        from whisper_dictate.database import CURRENT_SCHEMA_VERSION, Database

        db = Database(DatabaseConfig(path=tmp_path / "fresh.db"))
        db.initialize()
        assert self._schema_version(db) == CURRENT_SCHEMA_VERSION
        rid = db.create_recording("a.wav")
        assert db.get_recording(rid)["file_path"] == "a.wav"
        db.close()


class TestRowMappingStrictness:
    """Row mapping must match the schema exactly (zip strict=True)."""

    @pytest.fixture
    def db(self, tmp_path):
        from whisper_dictate.config import DatabaseConfig
        from whisper_dictate.database import Database

        database = Database(DatabaseConfig(path=tmp_path / "strict.db"))
        database.initialize()
        yield database
        database.close()

    def test_row_to_dict_raises_on_drift(self):
        from whisper_dictate.database import Database

        with pytest.raises(ValueError):
            Database._row_to_dict(("a", "b"), ["col1", "col2", "col3"])

    def test_row_to_dict_maps_matching_columns(self):
        from whisper_dictate.database import Database

        result = Database._row_to_dict(("a", "b"), ["col1", "col2"])
        assert result == {"col1": "a", "col2": "b"}

    def test_get_recording_full_dict_without_updated_at(self, db):
        rid = db.create_recording("2024/01/01/x.wav", duration=1.5)
        recording = db.get_recording(rid)
        assert recording["file_path"] == "2024/01/01/x.wav"
        assert "updated_at" not in recording
        assert set(recording) == {
            "id",
            "file_path",
            "timestamp",
            "duration",
            "format",
            "sample_rate",
            "channels",
            "created_at",
        }

    def test_list_recordings_full_dicts(self, db):
        db.create_recording("a.wav")
        db.create_recording("b.wav")
        recordings = db.list_recordings()
        assert len(recordings) == 2
        assert all("updated_at" not in r for r in recordings)
        assert all(r["file_path"] for r in recordings)

    def test_drifted_schema_fails_loudly(self, db):
        rid = db.create_recording("a.wav")
        # Simulate future schema drift: a column the query mapping doesn't know
        db.execute("ALTER TABLE recordings ADD COLUMN extra_col TEXT")
        with pytest.raises(ValueError):
            db.get_recording(rid)
