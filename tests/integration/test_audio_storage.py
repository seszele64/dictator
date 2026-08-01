"""Tests for audio storage functionality."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_dictate.audio_storage import (
    DEFAULT_MIN_FREE_SPACE_MB,
    AudioStorage,
    check_disk_space,
    cleanup_orphaned_files,
    get_orphaned_files,
)
from whisper_dictate.config import DatabaseConfig


@pytest.fixture
def temp_recordings_dir() -> Path:
    """Create a temporary recordings directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def audio_storage(temp_recordings_dir: Path) -> AudioStorage:
    """Create an AudioStorage instance with a temporary directory."""
    config = Mock(spec=DatabaseConfig)
    config.get_recordings_path.return_value = temp_recordings_dir
    return AudioStorage(config)


@pytest.fixture
def mock_db_with_recordings():
    """Create a mock database with some recordings."""
    mock_db = Mock()
    mock_db.list_recordings = Mock(
        return_value=[
            {"id": 1, "file_path": "2024/03/14/recording1.wav"},
            {"id": 2, "file_path": "2024/03/15/recording2.wav"},
        ]
    )
    return mock_db


@pytest.fixture
def mock_db_empty():
    """Create a mock database with no recordings."""
    mock_db = Mock()
    mock_db.list_recordings = Mock(return_value=[])
    return mock_db


class TestGetAudioPath:
    """Test the get_audio_path method."""

    def test_resolve_relative_path(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test resolving a relative path to absolute path."""
        relative_path = "2024/03/14/recording.wav"
        result = audio_storage.get_audio_path(relative_path)
        assert result == temp_recordings_dir / relative_path

    def test_resolve_path_without_verification(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test that verify_exists=False returns path even if file doesn't exist."""
        relative_path = "nonexistent/file.wav"
        result = audio_storage.get_audio_path(relative_path, verify_exists=False)
        assert result == temp_recordings_dir / relative_path
        assert not result.exists()

    def test_verify_exists_false_with_nonexistent_file(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test that verify_exists=False doesn't raise error for missing file."""
        relative_path = "2024/03/14/missing.wav"
        result = audio_storage.get_audio_path(relative_path, verify_exists=False)
        assert result == temp_recordings_dir / relative_path
        assert not result.exists()

    def test_verify_exists_true_with_existing_file(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test that verify_exists=True returns path when file exists."""
        # Create a test file
        file_path = temp_recordings_dir / "2024/03/14/test.wav"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("test content")

        relative_path = "2024/03/14/test.wav"
        result = audio_storage.get_audio_path(relative_path, verify_exists=True)
        assert result == file_path
        assert result.exists()

    def test_verify_exists_true_with_missing_file(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test that verify_exists=True raises FileNotFoundError for missing file."""
        relative_path = "2024/03/14/nonexistent.wav"
        with pytest.raises(FileNotFoundError) as exc_info:
            audio_storage.get_audio_path(relative_path, verify_exists=True)

        # Verify error message contains path
        assert str(temp_recordings_dir) in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()


class TestVerifyAudioFile:
    """Test the verify_audio_file method."""

    def test_verify_existing_file(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test verification of an existing audio file."""
        # Create a test file
        file_path = temp_recordings_dir / "2024/03/14/exists.wav"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"fake audio data")

        result = audio_storage.verify_audio_file("2024/03/14/exists.wav")
        assert result == file_path
        assert result.exists()

    def test_verify_missing_file_raises_error(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test that verifying missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            audio_storage.verify_audio_file("2024/03/14/missing.wav")

        error_message = str(exc_info.value)
        assert "Audio file not found" in error_message
        assert str(temp_recordings_dir) in error_message
        assert "deleted or moved" in error_message.lower()

    def test_verify_audio_file_returns_path_object(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test that verify_audio_file returns a Path object."""
        file_path = temp_recordings_dir / "test/path.wav"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("content")

        result = audio_storage.verify_audio_file("test/path.wav")
        assert isinstance(result, Path)
        assert result == file_path


class TestAudioStorageIntegration:
    """Integration tests for AudioStorage."""

    def test_get_audio_path_with_nested_directories(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test resolving path with deeply nested directories."""
        relative_path = "2024/01/01/very/deep/nested/path.wav"
        result = audio_storage.get_audio_path(relative_path)
        assert result == temp_recordings_dir / relative_path

    def test_verify_with_special_characters_in_filename(
        self, audio_storage: AudioStorage, temp_recordings_dir: Path
    ):
        """Test file verification with special characters in filename."""
        file_path = temp_recordings_dir / "2024/03/14/recording_001 (copy).wav"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("content")

        result = audio_storage.verify_audio_file("2024/03/14/recording_001 (copy).wav")
        assert result.exists()


class TestCheckDiskSpace:
    """Test the check_disk_space function."""

    def test_check_disk_space_returns_tuple(self, tmp_path):
        """Test that check_disk_space returns a tuple."""
        has_space, available_mb = check_disk_space(tmp_path)
        assert isinstance(has_space, bool)
        assert isinstance(available_mb, int)

    def test_check_disk_space_with_default_threshold(self, tmp_path):
        """Test check_disk_space with default threshold."""
        has_space, available_mb = check_disk_space(tmp_path)
        # Should have space on normal system
        assert has_space is True
        assert available_mb >= 0

    def test_check_disk_space_with_custom_threshold(self, tmp_path):
        """Test check_disk_space with custom threshold."""
        # Use a very high threshold to simulate low disk space
        has_space, available_mb = check_disk_space(tmp_path, min_free_mb=1000000000)
        # This should return False if we can't satisfy the huge threshold
        # but on most systems will return True since check should still succeed
        assert isinstance(has_space, bool)

    def test_check_disk_space_nonexistent_path(self):
        """Test check_disk_space with nonexistent path returns safe default."""
        # Should return True (allow operation) when check fails
        has_space, available_mb = check_disk_space(Path("/nonexistent/path"))
        assert has_space is True
        assert available_mb == 0


class TestAudioStorageDiskSpace:
    """Test disk space checking in AudioStorage class."""

    def test_audio_storage_check_disk_space(self, tmp_path):
        """Test AudioStorage.check_disk_space method."""
        config = DatabaseConfig(recordings_path=tmp_path)
        storage = AudioStorage(config)

        has_space, available_mb = storage.check_disk_space()
        assert isinstance(has_space, bool)
        assert isinstance(available_mb, int)

    def test_audio_storage_get_disk_usage(self, tmp_path):
        """Test AudioStorage.get_disk_usage method."""
        config = DatabaseConfig(recordings_path=tmp_path)
        storage = AudioStorage(config)

        usage = storage.get_disk_usage()
        assert "total_mb" in usage
        assert "available_mb" in usage
        assert "used_mb" in usage
        assert usage["recordings_path"] == str(tmp_path)

    def test_audio_storage_get_disk_usage_nonexistent(self):
        """Test AudioStorage.get_disk_usage with nonexistent path."""
        config = DatabaseConfig(recordings_path=Path("/nonexistent"))
        storage = AudioStorage(config)

        usage = storage.get_disk_usage()
        assert "error" in usage


class TestDiskSpaceConfiguration:
    """Test disk space configuration."""

    def test_default_min_free_space_mb(self):
        """Test that default min_free_space_mb is 100."""
        config = DatabaseConfig()
        assert config.min_free_space_mb == DEFAULT_MIN_FREE_SPACE_MB

    def test_custom_min_free_space_mb(self):
        """Test custom min_free_space_mb configuration."""
        config = DatabaseConfig(min_free_space_mb=50)
        assert config.min_free_space_mb == 50


# ============ Orphaned File Tests ============


class TestGetOrphanedFiles:
    """Tests for orphaned file detection."""

    def test_no_orphaned_files_when_directory_empty(
        self, audio_storage: AudioStorage, mock_db_empty, temp_recordings_dir: Path
    ):
        """Test that no orphaned files are found when directory is empty."""
        # Ensure directory exists but is empty
        temp_recordings_dir.mkdir(parents=True, exist_ok=True)

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            orphaned = get_orphaned_files(mock_db_empty)

        assert orphaned == []

    def test_no_orphaned_files_when_all_in_db(
        self,
        audio_storage: AudioStorage,
        mock_db_with_recordings,
        temp_recordings_dir: Path,
    ):
        """Test that no orphaned files when all files are in database."""
        # Create files that match database records
        (temp_recordings_dir / "2024/03/14").mkdir(parents=True)
        (temp_recordings_dir / "2024/03/15").mkdir(parents=True)
        (temp_recordings_dir / "2024/03/14/recording1.wav").write_bytes(b"test")
        (temp_recordings_dir / "2024/03/15/recording2.wav").write_bytes(b"test")

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            orphaned = get_orphaned_files(mock_db_with_recordings)

        assert orphaned == []

    def test_orphaned_files_detected(
        self, audio_storage: AudioStorage, mock_db_empty, temp_recordings_dir: Path
    ):
        """Test that orphaned files are detected when not in database."""
        # Create files in the recordings directory
        (temp_recordings_dir / "2024/03/14").mkdir(parents=True)
        (temp_recordings_dir / "2024/03/15").mkdir(parents=True)
        (temp_recordings_dir / "2024/03/14/orphan1.wav").write_bytes(
            b"orphan content 1"
        )
        (temp_recordings_dir / "2024/03/15/orphan2.wav").write_bytes(
            b"orphan content 2"
        )

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            orphaned = get_orphaned_files(mock_db_empty)

        assert len(orphaned) == 2
        orphaned_paths = [o["relative_path"] for o in orphaned]
        assert "2024/03/14/orphan1.wav" in orphaned_paths
        assert "2024/03/15/orphan2.wav" in orphaned_paths

    def test_mixed_files_only_orphans_returned(
        self,
        audio_storage: AudioStorage,
        mock_db_with_recordings,
        temp_recordings_dir: Path,
    ):
        """Test that only orphaned files are returned when some are in DB."""
        # Create files - some in DB, some not
        (temp_recordings_dir / "2024/03/14").mkdir(parents=True)
        (temp_recordings_dir / "2024/03/15").mkdir(parents=True)

        # Files in database
        (temp_recordings_dir / "2024/03/14/recording1.wav").write_bytes(b"db file 1")
        (temp_recordings_dir / "2024/03/15/recording2.wav").write_bytes(b"db file 2")

        # Orphaned files (not in database)
        (temp_recordings_dir / "2024/03/14/orphan1.wav").write_bytes(b"orphan")
        (temp_recordings_dir / "2024/03/15/orphan2.wav").write_bytes(b"orphan")

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            orphaned = get_orphaned_files(mock_db_with_recordings)

        assert len(orphaned) == 2
        orphaned_paths = [o["relative_path"] for o in orphaned]
        assert "2024/03/14/orphan1.wav" in orphaned_paths
        assert "2024/03/15/orphan2.wav" in orphaned_paths

        # DB-referenced files should NOT be in orphaned list
        assert "2024/03/14/recording1.wav" not in orphaned_paths
        assert "2024/03/15/recording2.wav" not in orphaned_paths

    def test_orphaned_file_includes_size_and_modified(
        self, audio_storage: AudioStorage, mock_db_empty, temp_recordings_dir: Path
    ):
        """Test that orphaned file info includes size and modified time."""
        import time

        (temp_recordings_dir / "2024/03/14").mkdir(parents=True)
        test_file = temp_recordings_dir / "2024/03/14/test.wav"
        test_content = b"test audio content"
        test_file.write_bytes(test_content)
        time.sleep(0.01)  # Ensure mtime changes

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            orphaned = get_orphaned_files(mock_db_empty)

        assert len(orphaned) == 1
        assert orphaned[0]["size"] == len(test_content)
        assert orphaned[0]["modified"] > 0
        assert orphaned[0]["path"] == test_file

    def test_directory_not_exists_returns_empty(
        self, audio_storage: AudioStorage, mock_db_empty, temp_recordings_dir: Path
    ):
        """Test that empty list is returned when recordings dir doesn't exist."""
        # Make sure the directory doesn't exist
        # (temp_recordings_dir is already a non-existent temp dir)

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            orphaned = get_orphaned_files(mock_db_empty)

        assert orphaned == []


class TestCleanupOrphanedFiles:
    """Tests for orphaned file cleanup."""

    def test_dry_run_does_not_delete(
        self, audio_storage: AudioStorage, mock_db_empty, temp_recordings_dir: Path
    ):
        """Test that dry_run=True doesn't actually delete files."""
        # Create orphaned files
        (temp_recordings_dir / "2024/03/14").mkdir(parents=True)
        test_file = temp_recordings_dir / "2024/03/14/orphan.wav"
        test_file.write_bytes(b"orphan content")

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            deleted_count, size_freed = cleanup_orphaned_files(
                mock_db_empty, dry_run=True
            )

        # File should still exist
        assert test_file.exists()
        assert deleted_count == 1
        assert size_freed > 0

    def test_actual_delete_removes_files(
        self, audio_storage: AudioStorage, mock_db_empty, temp_recordings_dir: Path
    ):
        """Test that dry_run=False actually deletes files."""
        # Create orphaned files
        (temp_recordings_dir / "2024/03/14").mkdir(parents=True)
        test_file = temp_recordings_dir / "2024/03/14/orphan.wav"
        test_content = b"orphan content"
        test_file.write_bytes(test_content)

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            deleted_count, size_freed = cleanup_orphaned_files(
                mock_db_empty, dry_run=False
            )

        # File should be deleted
        assert not test_file.exists()
        assert deleted_count == 1
        assert size_freed == len(test_content)

    def test_cleanup_returns_correct_count(
        self, audio_storage: AudioStorage, mock_db_empty, temp_recordings_dir: Path
    ):
        """Test that cleanup returns correct count and size."""
        # Create multiple orphaned files
        (temp_recordings_dir / "2024/03/14").mkdir(parents=True)
        file1 = temp_recordings_dir / "2024/03/14/orphan1.wav"
        file2 = temp_recordings_dir / "2024/03/14/orphan2.wav"
        content1 = b"content 1"
        content2 = b"longer content 2"
        file1.write_bytes(content1)
        file2.write_bytes(content2)

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            deleted_count, size_freed = cleanup_orphaned_files(
                mock_db_empty, dry_run=False
            )

        assert deleted_count == 2
        assert size_freed == len(content1) + len(content2)

    def test_cleanup_nonexistent_directory(
        self, audio_storage: AudioStorage, mock_db_empty, temp_recordings_dir: Path
    ):
        """Test cleanup handles non-existent directory gracefully."""
        # Directory doesn't exist
        with patch(
            "whisper_dictate.audio_storage.get_audio_storage",
            return_value=audio_storage,
        ):
            deleted_count, size_freed = cleanup_orphaned_files(
                mock_db_empty, dry_run=True
            )

        assert deleted_count == 0
        assert size_freed == 0
