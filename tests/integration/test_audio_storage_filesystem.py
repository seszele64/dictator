"""Filesystem integration tests for audio storage.

Covers the AudioStorage methods not already covered by
tests/integration/test_audio_storage.py (save/copy/delete/get, filename
generation, date directories, cleanup, stats, and singleton behavior).
"""

import re
import string
from datetime import datetime
from pathlib import Path

import pytest

from whisper_dictate.audio_storage import (
    AudioStorage,
    _generate_random_suffix,
    _generate_unique_filename,
    _get_date_based_path,
)
from whisper_dictate.config import DatabaseConfig


@pytest.fixture
def storage(tmp_path) -> AudioStorage:
    """Create an AudioStorage instance backed by a tmp_path directory."""
    return AudioStorage(DatabaseConfig(recordings_path=tmp_path / "recordings"))


class TestFilenameGeneration:
    """Tests for filename generation helpers."""

    def test_random_suffix_length(self):
        """Default random suffix is 8 characters."""
        assert len(_generate_random_suffix()) == 8

    def test_random_suffix_custom_length(self):
        """Custom suffix length is respected."""
        assert len(_generate_random_suffix(length=16)) == 16

    def test_random_suffix_charset(self):
        """Suffix uses only lowercase a-z and 0-9."""
        suffix = _generate_random_suffix()
        allowed = string.ascii_lowercase + string.digits
        assert all(c in allowed for c in suffix)

    def test_unique_filename_format(self):
        """Filename matches YYYYMMDD_HHMMSS_xxxxxxxx.wav."""
        assert re.fullmatch(r"\d{8}_\d{6}_[a-z0-9]{8}\.wav", _generate_unique_filename())

    def test_unique_filename_custom_suffix(self):
        """Custom suffix changes the file extension."""
        assert _generate_unique_filename(suffix="mp3").endswith(".mp3")

    def test_unique_filename_with_timestamp(self):
        """A specific timestamp appears in the filename."""
        timestamp = datetime(2026, 8, 1, 12, 30, 45)
        assert _generate_unique_filename(timestamp=timestamp).startswith("20260801_123045_")

    def test_unique_filename_uniqueness(self):
        """Generated filenames are unique across calls."""
        names = {_generate_unique_filename() for _ in range(100)}
        assert len(names) == 100


class TestDateBasedPath:
    """Tests for the _get_date_based_path helper."""

    def test_date_path_structure(self):
        """Path uses YYYY/MM/DD structure."""
        assert _get_date_based_path(Path("/tmp"), datetime(2026, 8, 1)) == Path("/tmp/2026/08/01")

    def test_date_path_default_now(self):
        """Without a timestamp, today's date is used."""
        now = datetime.now()
        result = _get_date_based_path(Path("/tmp"))
        assert result == Path("/tmp") / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}"

    def test_date_path_zero_padding(self):
        """Month and day are zero-padded."""
        assert _get_date_based_path(Path("/tmp"), datetime(2026, 1, 5)) == Path("/tmp/2026/01/05")


class TestAudioStorageInit:
    """Tests for AudioStorage construction."""

    def test_init_with_config(self, tmp_path):
        """recordings_path comes from the provided config."""
        storage = AudioStorage(DatabaseConfig(recordings_path=tmp_path / "recordings"))
        assert storage.recordings_path == tmp_path / "recordings"

    def test_init_default_config(self, env_isolator):
        """Explicit default config resolves XDG-based recordings path.

        (Config is REQUIRED since S2: no silent default-config fallback.)"""
        storage = AudioStorage(DatabaseConfig())
        assert storage.recordings_path == env_isolator / "data" / "whisper-dictate" / "recordings"

    def test_recordings_path_property(self, tmp_path):
        """recordings_path is read-only and returns the configured path."""
        storage = AudioStorage(DatabaseConfig(recordings_path=tmp_path / "rec"))
        assert storage.recordings_path == tmp_path / "rec"
        with pytest.raises(AttributeError):
            storage.recordings_path = tmp_path / "other"


class TestSaveAudio:
    """Tests for the save_audio method."""

    def test_save_audio_moves_file(self, storage, tmp_path):
        """save_audio moves the source file into persistent storage."""
        source = tmp_path / "source.wav"
        source.write_bytes(b"audio data")
        dest, relative = storage.save_audio(source)
        assert not source.exists()  # moved, not copied
        assert dest.exists()
        assert storage.recordings_path / relative == dest
        assert dest.read_bytes() == b"audio data"

    def test_save_audio_creates_date_directory(self, storage, tmp_path):
        """Files are stored in a YYYY/MM/DD subdirectory."""
        source = tmp_path / "source.wav"
        source.write_bytes(b"audio data")
        dest, _ = storage.save_audio(source, timestamp=datetime(2026, 8, 1, 10, 30, 0))
        assert dest.parent == storage.recordings_path / "2026" / "08" / "01"
        assert dest.parent.exists()

    def test_save_audio_relative_path_format(self, storage, tmp_path):
        """Relative path is POSIX-style and relative to recordings root."""
        source = tmp_path / "source.wav"
        source.write_bytes(b"audio data")
        dest, relative = storage.save_audio(source, timestamp=datetime(2026, 8, 1))
        assert "\\" not in relative
        assert relative.startswith("2026/08/01/")
        assert not Path(relative).is_absolute()
        assert storage.recordings_path / relative == dest

    def test_save_audio_source_not_found_raises(self, storage):
        """Saving a missing source raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            storage.save_audio(Path("/nonexistent.wav"))

    def test_save_audio_custom_suffix(self, storage, tmp_path):
        """Custom suffix changes the destination file extension."""
        source = tmp_path / "source.wav"
        source.write_bytes(b"audio data")
        dest, relative = storage.save_audio(source, suffix="mp3")
        assert dest.suffix == ".mp3"
        assert dest.name.endswith(".mp3")
        assert relative.endswith(".mp3")


class TestCopyAudio:
    """Tests for the copy_audio method."""

    def test_copy_audio_copies_file(self, storage, tmp_path):
        """copy_audio keeps the source and copies content to storage."""
        source = tmp_path / "source.wav"
        source.write_bytes(b"audio data")
        dest, _ = storage.copy_audio(source)
        assert source.exists()  # copy keeps original
        assert dest.exists()
        assert dest.read_bytes() == source.read_bytes()

    def test_copy_audio_creates_date_directory(self, storage, tmp_path):
        """Copied files land in a YYYY/MM/DD subdirectory."""
        source = tmp_path / "source.wav"
        source.write_bytes(b"audio data")
        dest, _ = storage.copy_audio(source, timestamp=datetime(2026, 8, 1))
        assert dest.parent == storage.recordings_path / "2026" / "08" / "01"

    def test_copy_audio_source_not_found_raises(self, storage):
        """Copying a missing source raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            storage.copy_audio(Path("/nonexistent.wav"))

    def test_copy_audio_custom_suffix(self, storage, tmp_path):
        """Custom suffix changes the copied file extension."""
        source = tmp_path / "source.wav"
        source.write_bytes(b"audio data")
        dest, _ = storage.copy_audio(source, suffix="mp3")
        assert dest.name.endswith(".mp3")
        assert source.exists()


class TestDeleteAudio:
    """Tests for the delete_audio method."""

    def test_delete_audio_existing_file(self, storage, tmp_path):
        """Deleting an existing file returns True and removes it."""
        source = tmp_path / "source.wav"
        source.write_bytes(b"audio data")
        _, relative = storage.save_audio(source)
        assert storage.delete_audio(relative) is True
        assert not storage.get_audio_path(relative).exists()

    def test_delete_audio_missing_file(self, storage):
        """Deleting a missing file returns False."""
        assert storage.delete_audio("nonexistent.wav") is False

    def test_delete_audio_does_not_raise_on_error(self, storage):
        """Deletion failures return False instead of raising."""
        target = storage.recordings_path / "dir.wav"
        target.mkdir(parents=True)
        assert storage.delete_audio("dir.wav") is False
        assert target.exists()


class TestGetAudio:
    """Tests for the get_audio method."""

    def test_get_audio_returns_bytes(self, storage, tmp_path):
        """get_audio returns the file contents as bytes."""
        source = tmp_path / "source.wav"
        source.write_bytes(b"audio data bytes")
        _, relative = storage.save_audio(source)
        assert storage.get_audio(relative) == b"audio data bytes"

    def test_get_audio_missing_returns_none(self, storage):
        """get_audio returns None for a missing file."""
        assert storage.get_audio("nonexistent.wav") is None


class TestGenerateStoragePath:
    """Tests for the generate_storage_path method."""

    def test_generate_storage_path_returns_tuple(self, storage):
        """Returns a (Path, filename) tuple."""
        result = storage.generate_storage_path()
        assert isinstance(result, tuple)
        path, filename = result
        assert isinstance(path, Path)
        assert isinstance(filename, str)

    def test_generate_storage_path_creates_directory(self, storage):
        """The date directory is created."""
        path, _ = storage.generate_storage_path()
        assert path.parent.exists()

    def test_generate_storage_path_filename_format(self, storage):
        """Filename matches YYYYMMDD_HHMMSS_xxxxxxxx.wav."""
        _, filename = storage.generate_storage_path()
        assert re.fullmatch(r"\d{8}_\d{6}_[a-z0-9]{8}\.wav", filename)


class TestGetDateDirectory:
    """Tests for the get_date_directory method."""

    def test_get_date_directory_creates_dir(self, storage):
        """get_date_directory creates and returns the date path."""
        directory = storage.get_date_directory(datetime(2026, 8, 1))
        assert directory == storage.recordings_path / "2026" / "08" / "01"
        assert directory.is_dir()

    def test_get_date_directory_no_create(self, storage):
        """create=False returns the path without creating it."""
        directory = storage.get_date_directory(datetime(2026, 8, 1), create=False)
        assert directory == storage.recordings_path / "2026" / "08" / "01"
        assert not directory.exists()


class TestEnsureDirectoryExists:
    """Tests for the ensure_directory_exists method."""

    def test_ensure_directory_creates_nested(self, storage):
        """Nested directory paths are created fully."""
        nested = storage.recordings_path / "a" / "b" / "c"
        storage.ensure_directory_exists(nested)
        assert nested.is_dir()

    def test_ensure_directory_existing_no_error(self, storage):
        """Existing directories are handled without error."""
        storage.ensure_directory_exists(storage.recordings_path)
        assert storage.recordings_path.is_dir()


class TestCleanupEmptyDirectories:
    """Tests for the cleanup_empty_directories method."""

    def test_cleanup_removes_empty_dirs(self, storage):
        """Empty year/month/day directories are all removed."""
        empty_dir = storage.recordings_path / "2026" / "08" / "01"
        empty_dir.mkdir(parents=True)
        removed = storage.cleanup_empty_directories()
        assert removed == 3
        assert not empty_dir.exists()
        assert not (storage.recordings_path / "2026").exists()

    def test_cleanup_keeps_non_empty_dirs(self, storage):
        """Directories containing files are preserved."""
        file_path = storage.recordings_path / "2026" / "08" / "01" / "file.wav"
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"data")
        removed = storage.cleanup_empty_directories()
        assert removed == 0
        assert file_path.exists()
        assert file_path.parent.exists()

    def test_cleanup_partial_removal(self, storage):
        """Only empty directories are removed."""
        file_path = storage.recordings_path / "2026" / "08" / "01" / "file.wav"
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"data")
        (storage.recordings_path / "2026" / "09").mkdir(parents=True)
        removed = storage.cleanup_empty_directories()
        assert removed == 1
        assert file_path.exists()
        assert not (storage.recordings_path / "2026" / "09").exists()
        assert (storage.recordings_path / "2026" / "08").exists()


class TestGetStorageStats:
    """Tests for the get_storage_stats method."""

    def test_storage_stats_empty(self, storage):
        """Empty recordings directory reports zero stats."""
        storage.recordings_path.mkdir(parents=True)
        stats = storage.get_storage_stats()
        assert stats["total_files"] == 0
        assert stats["total_size_bytes"] == 0

    def test_storage_stats_with_files(self, storage, tmp_path):
        """Files and their sizes are counted."""
        for i in range(2):
            source = tmp_path / f"source{i}.wav"
            source.write_bytes(b"x" * (10 + i))
            storage.save_audio(source)
        stats = storage.get_storage_stats()
        assert stats["total_files"] == 2
        assert stats["total_size_bytes"] == 10 + 11

    def test_storage_stats_no_recordings_dir(self, storage):
        """Missing recordings directory reports zero stats."""
        stats = storage.get_storage_stats()
        assert stats["total_files"] == 0
        assert stats["total_size_bytes"] == 0
