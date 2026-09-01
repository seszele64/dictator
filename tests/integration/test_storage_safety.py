"""Regression tests for storage path safety and atomic, claim-first saves.

Covers the fix-storage-safety defects:
- get_audio_path blind-join path escape (absolute paths, .. traversal, symlinks)
- empty file_path sentinel (was resolving to the recordings root itself)
- save_audio staging + os.replace atomicity (no partial files at the final path)
- orphan scan skipping in-progress staging files
"""

import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_dictate.audio_storage import (
    STAGING_PREFIX,
    AudioStorage,
    NoAudioFileError,
    UnsafeAudioPathError,
    get_orphaned_files,
)
from whisper_dictate.config import DatabaseConfig
from whisper_dictate.database import Database


@pytest.fixture
def recordings_root(tmp_path) -> Path:
    root = tmp_path / "recordings"
    root.mkdir()
    return root


@pytest.fixture
def storage(recordings_root: Path) -> AudioStorage:
    return AudioStorage(DatabaseConfig(recordings_path=recordings_root))


class TestPathContainment:
    """Stored paths must never resolve outside the recordings root."""

    def test_normal_relative_path_resolves_inside_root(self, storage, recordings_root):
        result = storage.get_audio_path("2024/03/14/rec.wav")
        assert result == recordings_root.resolve() / "2024/03/14/rec.wav"

    def test_absolute_path_outside_root_rejected(self, storage, tmp_path):
        outside = tmp_path / "outside.wav"
        outside.write_bytes(b"x")
        with pytest.raises(UnsafeAudioPathError):
            storage.get_audio_path(str(outside))

    def test_dotdot_traversal_rejected(self, storage):
        with pytest.raises(UnsafeAudioPathError):
            storage.get_audio_path("../../etc/hostname")

    def test_path_resolving_to_root_itself_rejected(self, storage):
        with pytest.raises(UnsafeAudioPathError):
            storage.get_audio_path(".")

    def test_empty_path_is_no_file_sentinel(self, storage):
        with pytest.raises(NoAudioFileError):
            storage.get_audio_path("")
        with pytest.raises(NoAudioFileError):
            storage.get_audio_path("   ")

    def test_legacy_absolute_path_inside_root_accepted(self, storage, recordings_root):
        legacy = recordings_root / "2024/01/01/legacy.wav"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"audio")
        result = storage.get_audio_path(str(legacy))
        assert result == legacy.resolve()

    def test_symlink_escape_rejected(self, storage, recordings_root, tmp_path):
        outside = tmp_path / "secret.wav"
        outside.write_bytes(b"secret")
        link = recordings_root / "link.wav"
        link.symlink_to(outside)
        with pytest.raises(UnsafeAudioPathError):
            storage.get_audio_path("link.wav")

    def test_delete_audio_never_removes_outside_root(
        self, storage, recordings_root, tmp_path
    ):
        outside = tmp_path / "precious.wav"
        outside.write_bytes(b"keep me")
        assert storage.delete_audio(str(outside)) is False
        assert outside.exists()


class TestAtomicSave:
    """Saves stage inside the destination dir and finalize with os.replace."""

    def test_stage_and_finalize_produces_complete_file(self, storage, recordings_root):
        source = recordings_root / "source.wav"
        source.write_bytes(b"complete audio content")

        staged = storage.stage_audio(source, suffix="wav")
        assert staged.staged_path.name.startswith(STAGING_PREFIX)
        assert staged.staged_path.parent == staged.final_path.parent
        assert staged.staged_path.read_bytes() == b"complete audio content"
        assert not staged.final_path.exists()  # nothing at the final path yet

        final = storage.finalize_audio(staged)
        assert final == staged.final_path
        assert final.read_bytes() == b"complete audio content"
        assert not staged.staged_path.exists()

    def test_save_audio_wrapper_returns_final_and_relative(
        self, storage, recordings_root
    ):
        source = recordings_root / "source.mp3"
        source.write_bytes(b"mp3 data")
        final, relative = storage.save_audio(source, suffix="mp3")
        assert final.exists()
        assert relative == str(final.relative_to(recordings_root))

    def test_finalize_failure_leaves_no_partial_file_and_cleans_staging(
        self, storage, recordings_root
    ):
        source = recordings_root / "source.wav"
        source.write_bytes(b"data")
        staged = storage.stage_audio(source)

        with patch(
            "whisper_dictate.audio_storage.os.replace", side_effect=OSError("ENOSPC")
        ), pytest.raises(OSError, match="Failed to finalize"):
            storage.finalize_audio(staged)

        assert not staged.final_path.exists()  # no partial file ever appeared
        assert not staged.staged_path.exists()  # staging file cleaned up

    def test_stage_failure_cleans_up_partial_staging_file(
        self, storage, recordings_root
    ):
        source = recordings_root / "source.wav"
        source.write_bytes(b"data")
        with patch(
            "whisper_dictate.audio_storage.shutil.copy2", side_effect=OSError("disk full")
        ), pytest.raises(OSError, match="Failed to stage"):
            storage.stage_audio(source)
        # No staging leftovers anywhere in the tree
        assert not any(recordings_root.rglob(f"{STAGING_PREFIX}*"))

    def test_stage_missing_source_raises_file_not_found(self, storage):
        with pytest.raises(FileNotFoundError):
            storage.stage_audio(Path("/nonexistent-source.wav"))


class TestOrphanScanStagingFiles:
    """The orphan scan must not race in-progress staging saves."""

    def _db_with(self, file_paths):
        db = Mock()
        db.list_recordings = Mock(
            return_value=[{"id": i, "file_path": p} for i, p in enumerate(file_paths)]
        )
        return db

    def test_recent_staging_file_is_not_orphaned(self, storage, recordings_root):
        staging = recordings_root / "2024/01/01"
        staging.mkdir(parents=True)
        staged_file = staging / f"{STAGING_PREFIX}x.wav.abc123.part"
        staged_file.write_bytes(b"partial")

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage", return_value=storage
        ):
            orphaned = get_orphaned_files(self._db_with([]))

        assert orphaned == []
        assert staged_file.exists()

    def test_old_staging_file_is_orphaned_and_cleaned(self, storage, recordings_root):
        staging = recordings_root / "2024/01/01"
        staging.mkdir(parents=True)
        staged_file = staging / f"{STAGING_PREFIX}old.wav.abc123.part"
        staged_file.write_bytes(b"leftover")
        old = time.time() - 7200
        os.utime(staged_file, (old, old))

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage", return_value=storage
        ):
            deleted, _ = get_orphaned_files_and_cleanup(self._db_with([]))

        assert not staged_file.exists()
        assert deleted == 1

    def test_empty_and_unsafe_db_paths_are_ignored(self, storage, recordings_root):
        # A row with an empty path (silence sentinel) and one with a path
        # outside the root must not make any file show up as referenced.
        day_dir = recordings_root / "2024/01/01"
        day_dir.mkdir(parents=True)
        (day_dir / "orphan.wav").write_bytes(b"orphan")

        db = self._db_with(["", str(recordings_root.parent / "elsewhere.wav")])
        with patch(
            "whisper_dictate.audio_storage.get_audio_storage", return_value=storage
        ):
            orphaned = get_orphaned_files(db)

        assert [o["relative_path"] for o in orphaned] == ["2024/01/01/orphan.wav"]

    def test_legacy_absolute_in_root_path_is_not_orphaned(
        self, storage, recordings_root
    ):
        day_dir = recordings_root / "2024/01/01"
        day_dir.mkdir(parents=True)
        referenced = day_dir / "rec.wav"
        referenced.write_bytes(b"referenced")

        db = self._db_with([str(referenced)])  # legacy absolute form
        with patch(
            "whisper_dictate.audio_storage.get_audio_storage", return_value=storage
        ):
            orphaned = get_orphaned_files(db)

        assert orphaned == []


class TestOrphanScanSymlinkedRoot:
    """The orphan scan must compare resolved-vs-resolved paths.

    Regression test for the Kilo review WARNING on PR #25: the filesystem
    scan keyed files against the raw configured recordings root while the DB
    side resolves paths through get_audio_path(), so a symlinked recordings
    root made every real recording look orphaned (mass-deletion hazard for
    `audio cleanup --confirm`).
    """

    @pytest.fixture
    def symlinked_setup(self, tmp_path):
        real_root = tmp_path / "real-recordings"
        real_root.mkdir()
        link = tmp_path / "linked-recordings"
        link.symlink_to(real_root, target_is_directory=True)
        config = DatabaseConfig(path=tmp_path / "test.db", recordings_path=link)
        storage = AudioStorage(config)
        db = Database(config)
        db.initialize()
        return storage, db, link, real_root

    def test_stored_recording_is_not_orphaned_through_symlink(
        self, symlinked_setup
    ):
        storage, db, link, real_root = symlinked_setup
        source = link / "source.wav"
        source.write_bytes(b"real recording")
        final, relative = storage.save_audio(source)
        db.create_recording(file_path=relative, duration=2.5, format="wav")

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage", return_value=storage
        ):
            orphaned = get_orphaned_files(db)
            deleted, _ = get_orphaned_files_and_cleanup(db)

        assert orphaned == []
        assert deleted == 0
        assert final.exists()  # the real file survived cleanup

    def test_untracked_file_in_symlinked_root_is_orphaned(self, symlinked_setup):
        storage, db, link, real_root = symlinked_setup
        day_dir = link / "2024/01/01"
        day_dir.mkdir(parents=True)
        stray = day_dir / "stray.wav"
        stray.write_bytes(b"untracked")

        with patch(
            "whisper_dictate.audio_storage.get_audio_storage", return_value=storage
        ):
            orphaned = get_orphaned_files(db)

        assert [o["relative_path"] for o in orphaned] == ["2024/01/01/stray.wav"]
        assert stray.exists()  # get_orphaned_files only reports, never deletes


def get_orphaned_files_and_cleanup(db):
    from whisper_dictate.audio_storage import cleanup_orphaned_files

    return cleanup_orphaned_files(db, dry_run=False)
