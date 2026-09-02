"""Unit tests for the whisper_dictate.migration module.

These tests use a fully mocked database and monkeypatched legacy file paths,
so no real filesystem or SQLite state is touched.
"""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from whisper_dictate.migration import (
    MIGRATION_COMPLETED,
    MIGRATION_FAILED,
    MIGRATION_STATUS_KEY,
    MigrationError,
    MigrationManager,
    check_migration_status,
    run_migration,
)


@pytest.fixture
def mock_migration_db():
    """Provide a mocked database and patch Database() to return it."""
    db = Mock()
    db.initialize = Mock()
    db.close = Mock()
    db.get_state = Mock(return_value=None)
    db.set_state = Mock()
    db.delete_state = Mock()
    db.transaction = MagicMock()
    db.transaction.return_value.__enter__ = Mock(return_value=None)
    db.transaction.return_value.__exit__ = Mock(return_value=False)
    with patch("whisper_dictate.migration.Database", return_value=db):
        yield db


@pytest.fixture
def tmp_legacy_paths(tmp_path, monkeypatch):
    """Point the legacy file constants at temp paths."""
    state = tmp_path / "state"
    pid = tmp_path / "pid"
    audio = tmp_path / "audio.wav"
    backup = tmp_path / "backups"
    monkeypatch.setattr("whisper_dictate.migration.LEGACY_STATE_FILE", state)
    monkeypatch.setattr("whisper_dictate.migration.LEGACY_PID_FILE", pid)
    monkeypatch.setattr("whisper_dictate.migration.LEGACY_AUDIO_FILE", audio)
    monkeypatch.setattr("whisper_dictate.migration.BACKUP_DIR", backup)
    return {"state": state, "pid": pid, "audio": audio, "backup": backup}


def _configure_successful_verify(db, force: bool = False) -> None:
    """Configure get_state so migration proceeds and verification passes.

    In non-force mode the very first get_state call is the
    is_migration_completed() check, which must return None (not completed) so
    the migration is not skipped. Subsequent calls during _verify_migration
    return valid per-key data. In force mode is_migration_completed() never
    queries, so every call belongs to verification.
    """
    calls = {"count": 0}

    def side_effect(key: str):
        calls["count"] += 1
        if not force and calls["count"] == 1:
            return None
        if key == "legacy_recording_state":
            return {
                "is_recording": True,
                "migrated_at": "2026-01-01T00:00:00",
                "source": "legacy_state_file",
            }
        if key == "legacy_pid_state":
            return {
                "has_pid": True,
                "migrated_at": "2026-01-01T00:00:00",
                "source": "legacy_pid_file",
            }
        if key == MIGRATION_STATUS_KEY:
            return {"status": MIGRATION_COMPLETED}
        return None

    db.get_state.side_effect = side_effect


class TestDetectLegacyFiles:
    """Tests for detect_legacy_files()."""

    def test_detect_no_files(self, mock_migration_db, tmp_legacy_paths):
        manager = MigrationManager()
        assert manager.detect_legacy_files() == {
            "state_file": False,
            "pid_file": False,
            "audio_file": False,
        }

    def test_detect_all_files(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        tmp_legacy_paths["pid"].write_text("12345")
        tmp_legacy_paths["audio"].write_bytes(b"fake audio")
        manager = MigrationManager()
        assert manager.detect_legacy_files() == {
            "state_file": True,
            "pid_file": True,
            "audio_file": True,
        }

    def test_detect_partial_files(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        manager = MigrationManager()
        assert manager.detect_legacy_files() == {
            "state_file": True,
            "pid_file": False,
            "audio_file": False,
        }


class TestIsMigrationCompleted:
    """Tests for is_migration_completed()."""

    def test_not_completed_no_state(self, mock_migration_db):
        mock_migration_db.get_state.return_value = None
        manager = MigrationManager()
        assert manager.is_migration_completed() is False

    def test_completed(self, mock_migration_db):
        mock_migration_db.get_state.return_value = {"status": "completed"}
        manager = MigrationManager()
        assert manager.is_migration_completed() is True

    def test_force_always_false(self, mock_migration_db):
        mock_migration_db.get_state.return_value = {"status": "completed"}
        manager = MigrationManager()
        assert manager.is_migration_completed(force=True) is False


class TestRunMigrationSkipped:
    """Tests for run_migration() skip paths."""

    def test_skip_already_completed(self, mock_migration_db, tmp_legacy_paths):
        mock_migration_db.get_state.return_value = {"status": "completed"}
        manager = MigrationManager()
        result = manager.run_migration()
        assert result == {
            "success": True,
            "skipped": True,
            "message": "Migration already completed",
        }
        mock_migration_db.set_state.assert_not_called()

    def test_skip_no_legacy_files(self, mock_migration_db, tmp_legacy_paths):
        mock_migration_db.get_state.return_value = None
        manager = MigrationManager()
        result = manager.run_migration()
        assert result == {
            "success": True,
            "skipped": True,
            "message": "No legacy files to migrate",
        }
        mock_migration_db.set_state.assert_called_once()
        key, payload = mock_migration_db.set_state.call_args.args
        assert key == MIGRATION_STATUS_KEY
        assert payload["status"] == MIGRATION_COMPLETED

    def test_force_re_migration(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        tmp_legacy_paths["pid"].write_text("12345")
        _configure_successful_verify(mock_migration_db, force=True)
        manager = MigrationManager()
        result = manager.run_migration(force=True)
        assert result["success"] is True
        assert result["skipped"] is False
        keys = [call.args[0] for call in mock_migration_db.set_state.call_args_list]
        assert "legacy_recording_state" in keys
        assert "legacy_pid_state" in keys
        assert MIGRATION_STATUS_KEY in keys


class TestRunMigrationSuccess:
    """Tests for run_migration() successful migration paths."""

    def test_full_migration_state_and_pid(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        tmp_legacy_paths["pid"].write_text("12345")
        _configure_successful_verify(mock_migration_db)
        manager = MigrationManager()
        result = manager.run_migration()
        assert result["success"] is True
        assert result["skipped"] is False
        assert isinstance(result["migrated_files"], dict)
        assert result["migrated_files"]["state_file"] is True
        assert result["migrated_files"]["pid_file"] is True
        assert isinstance(result["backup_path"], str)
        keys = [call.args[0] for call in mock_migration_db.set_state.call_args_list]
        assert "legacy_recording_state" in keys
        assert "legacy_pid_state" in keys
        assert MIGRATION_STATUS_KEY in keys
        mock_migration_db.delete_state.assert_not_called()
        assert not tmp_legacy_paths["state"].exists()
        assert not tmp_legacy_paths["pid"].exists()

    def test_migration_state_only(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        _configure_successful_verify(mock_migration_db)
        manager = MigrationManager()
        result = manager.run_migration()
        assert result["success"] is True
        keys = [call.args[0] for call in mock_migration_db.set_state.call_args_list]
        assert "legacy_recording_state" in keys
        assert MIGRATION_STATUS_KEY in keys
        assert "legacy_pid_state" not in keys

    def test_migration_backup_created(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        tmp_legacy_paths["pid"].write_text("12345")
        tmp_legacy_paths["audio"].write_bytes(b"fake audio")
        _configure_successful_verify(mock_migration_db)
        manager = MigrationManager()
        result = manager.run_migration()
        assert result["success"] is True
        backup_dir = Path(result["backup_path"])
        assert backup_dir.exists()
        assert (backup_dir / "state").exists()
        assert (backup_dir / "pid").exists()
        assert (backup_dir / "audio.wav").exists()


class TestRunMigrationFailure:
    """Tests for run_migration() failure and rollback paths."""

    def test_backup_failure_aborts(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        with patch(
            "whisper_dictate.migration.shutil.copy2",
            side_effect=OSError("disk full"),
        ):
            manager = MigrationManager()
            with pytest.raises(MigrationError):
                manager.run_migration()
        status_calls = [
            call
            for call in mock_migration_db.set_state.call_args_list
            if call.args[0] == MIGRATION_STATUS_KEY
        ]
        assert status_calls
        assert status_calls[-1].args[1]["status"] == MIGRATION_FAILED

    def test_verify_failure_triggers_rollback(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        tmp_legacy_paths["pid"].write_text("12345")
        # get_state returns None everywhere, so verification fails and rollback runs
        mock_migration_db.get_state.return_value = None
        manager = MigrationManager()
        with pytest.raises(MigrationError):
            manager.run_migration()
        mock_migration_db.delete_state.assert_any_call("legacy_recording_state")
        mock_migration_db.delete_state.assert_any_call("legacy_pid_state")
        status_calls = [
            call
            for call in mock_migration_db.set_state.call_args_list
            if call.args[0] == MIGRATION_STATUS_KEY
        ]
        assert status_calls[-1].args[1]["status"] == MIGRATION_FAILED

    def test_pid_parse_failure_does_not_abort(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        tmp_legacy_paths["pid"].write_text("not_a_number")
        _configure_successful_verify(mock_migration_db)
        manager = MigrationManager()
        result = manager.run_migration()  # must not raise
        assert result["success"] is True
        assert result["skipped"] is False
        pid_calls = [
            call
            for call in mock_migration_db.set_state.call_args_list
            if call.args[0] == "legacy_pid_state"
        ]
        assert len(pid_calls) == 1
        payload = pid_calls[0].args[1]
        assert "pid" not in payload
        # Production code computes has_pid = (parsed_pid is not None), so an
        # unparseable PID yields has_pid=False (with no "pid" key).
        assert payload["has_pid"] is False


class TestMigrationLog:
    """Tests for get_migration_log()."""

    def test_get_migration_log_returns_copy(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        _configure_successful_verify(mock_migration_db)
        manager = MigrationManager()
        manager.run_migration()
        log = manager.get_migration_log()
        assert isinstance(log, list)
        assert len(log) > 0
        for entry in log:
            assert "timestamp" in entry
            assert "level" in entry
            assert "message" in entry
        # Mutating the returned copy must not affect internal state
        log.clear()
        second = manager.get_migration_log()
        assert len(second) > 0


class TestCheckMigrationStatus:
    """Tests for the module-level check_migration_status()."""

    def test_status_no_legacy_no_completion(self, mock_migration_db, tmp_legacy_paths):
        mock_migration_db.get_state.return_value = None
        result = check_migration_status()
        assert result["has_legacy_files"] is False
        assert result["migration_completed"] is False
        assert result["migration_needed"] is False

    def test_status_legacy_not_completed(self, mock_migration_db, tmp_legacy_paths):
        tmp_legacy_paths["state"].write_text("recording")
        mock_migration_db.get_state.return_value = None
        result = check_migration_status()
        assert result["has_legacy_files"] is True
        assert result["migration_completed"] is False
        assert result["migration_needed"] is True


class TestModuleLevelErrorPropagation:
    """W1 regression: the module-level run_migration()/check_migration_status()
    wrappers must propagate the ORIGINAL exception raised inside their
    try/finally - never a masked or replacement error (a regression here
    surfaced as NameError instead of the real failure).
    """

    def test_run_migration_backup_failure_propagates_migration_error(
        self, mock_migration_db, tmp_legacy_paths
    ):
        """A failed backup copy aborts via MigrationError through the wrapper."""
        tmp_legacy_paths["state"].write_text("recording")
        with (
            patch(
                "whisper_dictate.migration.shutil.copy2",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(MigrationError, match="Backup creation failed"),
        ):
            run_migration()

    def test_run_migration_inner_failure_not_masked_by_status_write(
        self, mock_migration_db, tmp_legacy_paths
    ):
        """The best-effort FAILED-status write must not replace the original
        migration error with the secondary failure."""
        tmp_legacy_paths["state"].write_text("recording")
        mock_migration_db.transaction.return_value.__enter__ = Mock(
            side_effect=RuntimeError("db went away mid-migration")
        )
        mock_migration_db.set_state = Mock(
            side_effect=RuntimeError("status write failed")
        )
        with pytest.raises(MigrationError, match="db went away mid-migration"):
            run_migration()

    def test_check_migration_status_init_failure_propagates_original_error(
        self, mock_migration_db, tmp_legacy_paths
    ):
        """An initialize failure inside check_migration_status propagates the
        wrapped MigrationError, not a masked replacement."""
        mock_migration_db.initialize = Mock(
            side_effect=RuntimeError("cannot open database")
        )
        with pytest.raises(
            MigrationError, match="Failed to initialize database"
        ):
            check_migration_status()
