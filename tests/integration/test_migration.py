"""Integration tests for the whisper_dictate.migration module.

These tests use a real SQLite database (temp file) and real files on the
filesystem. No database or filesystem calls are mocked.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from whisper_dictate.database import Database
from whisper_dictate.migration import (
    MIGRATION_COMPLETED,
    MIGRATION_FAILED,
    MIGRATION_STATUS_KEY,
    MigrationError,
    MigrationManager,
    check_migration_status,
)


@pytest.fixture
def migration_manager(real_db_config, tmp_path, monkeypatch):
    """Create a real MigrationManager backed by a temp SQLite DB and temp files."""
    state = tmp_path / "state"
    pid = tmp_path / "pid"
    audio = tmp_path / "audio.wav"
    backup = tmp_path / "backups"
    monkeypatch.setattr("whisper_dictate.migration.LEGACY_STATE_FILE", state)
    monkeypatch.setattr("whisper_dictate.migration.LEGACY_PID_FILE", pid)
    monkeypatch.setattr("whisper_dictate.migration.LEGACY_AUDIO_FILE", audio)
    monkeypatch.setattr("whisper_dictate.migration.BACKUP_DIR", backup)
    # Per-instance Database (no singleton): the manager owns this one, and
    # tests needing check_migration_status() pass the same instance via db=.
    db = Database(real_db_config)
    manager = MigrationManager(db=db)
    manager.initialize()
    yield manager
    manager.close()


class TestRunMigrationReal:
    """Integration tests for run_migration() with a real database."""

    def test_full_migration_real(self, migration_manager, tmp_path):
        state = tmp_path / "state"
        pid = tmp_path / "pid"
        audio = tmp_path / "audio.wav"
        state.write_text("recording")
        pid.write_text("12345")
        audio.write_bytes(b"fake audio")

        result = migration_manager.run_migration()

        assert result["success"] is True
        assert result["skipped"] is False
        assert isinstance(result["backup_path"], str)

        recording_state = migration_manager._db.get_state("legacy_recording_state")
        assert recording_state["is_recording"] is True
        assert "migrated_at" in recording_state
        assert recording_state["source"] == "legacy_state_file"
        assert recording_state["content"] == "recording"

        pid_state = migration_manager._db.get_state("legacy_pid_state")
        assert pid_state["has_pid"] is True
        assert pid_state["pid"] == 12345
        assert "process_exists" in pid_state

        status = migration_manager._db.get_state(MIGRATION_STATUS_KEY)
        assert status["status"] == MIGRATION_COMPLETED

        # Legacy files removed, audio kept (it contains real recording data)
        assert not state.exists()
        assert not pid.exists()
        assert audio.exists()

        # Backup contains copies of every legacy file
        backup_dir = Path(result["backup_path"])
        assert backup_dir.exists()
        assert (backup_dir / "state").exists()
        assert (backup_dir / "pid").exists()
        assert (backup_dir / "audio.wav").exists()

    def test_migration_skip_when_completed_real(self, migration_manager, tmp_path):
        migration_manager._db.set_state(MIGRATION_STATUS_KEY, {"status": MIGRATION_COMPLETED})
        state = tmp_path / "state"
        pid = tmp_path / "pid"
        state.write_text("recording")
        pid.write_text("12345")

        result = migration_manager.run_migration()

        assert result["success"] is True
        assert result["skipped"] is True
        assert result["message"] == "Migration already completed"
        # Skipped migrations must not touch legacy files
        assert state.exists()
        assert pid.exists()

    def test_force_re_migration_real(self, migration_manager, tmp_path):
        migration_manager._db.set_state(MIGRATION_STATUS_KEY, {"status": MIGRATION_COMPLETED})
        state = tmp_path / "state"
        pid = tmp_path / "pid"
        state.write_text("recording")
        pid.write_text("12345")

        result = migration_manager.run_migration(force=True)

        assert result["success"] is True
        assert result["skipped"] is False
        assert not state.exists()
        assert not pid.exists()
        recording_state = migration_manager._db.get_state("legacy_recording_state")
        assert recording_state is not None
        assert recording_state["is_recording"] is True
        assert recording_state["content"] == "recording"

    def test_no_legacy_files_sets_completed_real(self, migration_manager):
        result = migration_manager.run_migration()

        assert result["success"] is True
        assert result["skipped"] is True
        assert result["message"] == "No legacy files to migrate"
        status = migration_manager._db.get_state(MIGRATION_STATUS_KEY)
        assert status is not None
        assert status["status"] == MIGRATION_COMPLETED

    def test_rollback_on_failure_real(self, migration_manager, tmp_path):
        state = tmp_path / "state"
        pid = tmp_path / "pid"
        state.write_text("recording")
        pid.write_text("12345")

        with (
            patch.object(migration_manager, "_migrate_pid", side_effect=RuntimeError("boom")),
            pytest.raises(MigrationError),
        ):
            migration_manager.run_migration()

        # Migrated state was rolled back and status marked failed
        assert migration_manager._db.get_state("legacy_recording_state") is None
        status = migration_manager._db.get_state(MIGRATION_STATUS_KEY)
        assert status["status"] == MIGRATION_FAILED

        # Backup is preserved for manual recovery
        backup_dir = tmp_path / "backups"
        subdirs = list(backup_dir.iterdir()) if backup_dir.exists() else []
        assert len(subdirs) >= 1
        assert subdirs[0].is_dir()
        assert (subdirs[0] / "state").exists()
        assert (subdirs[0] / "pid").exists()


class TestCheckMigrationStatusReal:
    """Integration tests for check_migration_status() with a real database."""

    def test_status_no_files_real(self, migration_manager):
        result = check_migration_status(db=migration_manager._db)
        assert result["migration_needed"] is False
        assert result["has_legacy_files"] is False
        assert result["migration_completed"] is False

    def test_status_files_present_real(self, migration_manager, tmp_path):
        (tmp_path / "state").write_text("recording")
        (tmp_path / "pid").write_text("12345")

        result = check_migration_status(db=migration_manager._db)

        assert result["migration_needed"] is True
        assert result["has_legacy_files"] is True
        assert result["migration_completed"] is False

    def test_status_after_migration_real(self, migration_manager, tmp_path):
        (tmp_path / "state").write_text("recording")
        (tmp_path / "pid").write_text("12345")

        migration_manager.run_migration()
        result = check_migration_status(db=migration_manager._db)

        assert result["migration_needed"] is False
        assert result["migration_completed"] is True
        assert result["has_legacy_files"] is False
