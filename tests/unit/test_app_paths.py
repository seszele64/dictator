"""Tests for AppPaths — the single source of truth for filesystem paths (P2).

Covers:
- XDG Base Directory resolution defaults (env unset)
- XDG_DATA_HOME / XDG_STATE_HOME overrides
- DatabaseConfig override precedence over the AppPaths defaults
- The shared legacy dotfile contract between whisper_dictate.toggle and migration
- AppConfig.paths call-time env semantics (computed property, not a snapshot)
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from whisper_dictate.config import AppConfig, AppPaths, DatabaseConfig


@pytest.fixture
def clean_xdg_env(monkeypatch):
    """Remove XDG overrides so the spec defaults (~/.local/...) are observable."""
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    return monkeypatch


class TestAppPathsDefaults:
    """AppPaths resolves XDG Base Directory defaults when env vars are unset."""

    def test_data_home_default(self, clean_xdg_env):
        """Without XDG_DATA_HOME, data home is ~/.local/share/whisper-dictate."""
        assert AppPaths().data_home == Path.home() / ".local" / "share" / "whisper-dictate"

    def test_log_dir_default(self, clean_xdg_env):
        """Without XDG_STATE_HOME, logs live under ~/.local/state (XDG state, not data)."""
        assert AppPaths().log_dir == Path.home() / ".local" / "state" / "whisper-dictate" / "logs"

    def test_log_file_derived_from_log_dir(self, clean_xdg_env):
        """log_file is whisper-dictate.log inside log_dir."""
        paths = AppPaths()
        assert paths.log_file == paths.log_dir / "whisper-dictate.log"

    def test_backup_dir_derived_from_data_home(self, clean_xdg_env):
        """backup_dir is always data_home/backups (cannot drift from data home)."""
        paths = AppPaths()
        assert paths.backup_dir == paths.data_home / "backups"

    def test_legacy_paths_default(self, clean_xdg_env):
        """Legacy dotfiles live directly in $HOME."""
        paths = AppPaths()
        assert paths.legacy_state_file == Path.home() / ".whisper-dictate-state"
        assert paths.legacy_pid_file == Path.home() / ".whisper-dictate-pid"
        assert paths.legacy_audio_file == Path.home() / ".whisper-dictate-audio.wav"


class TestAppPathsEnvOverrides:
    """XDG env vars are honored at AppPaths instantiation time."""

    def test_xdg_data_home_override(self, monkeypatch, tmp_path):
        """XDG_DATA_HOME redirects data home (and its derived paths)."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        paths = AppPaths()
        assert paths.data_home == tmp_path / "data" / "whisper-dictate"
        assert paths.backup_dir == tmp_path / "data" / "whisper-dictate" / "backups"

    def test_xdg_state_home_override(self, monkeypatch, tmp_path):
        """XDG_STATE_HOME redirects the log directory (and log_file with it)."""
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        paths = AppPaths()
        assert paths.log_dir == tmp_path / "state" / "whisper-dictate" / "logs"
        assert paths.log_file == tmp_path / "state" / "whisper-dictate" / "logs" / "whisper-dictate.log"

    def test_state_home_does_not_affect_data_home(self, monkeypatch, tmp_path, tmp_path_factory):
        """XDG_STATE_HOME only moves logs; data home stays on XDG_DATA_HOME."""
        data = tmp_path_factory.mktemp("data")
        monkeypatch.setenv("XDG_DATA_HOME", str(data))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        paths = AppPaths()
        assert paths.data_home == data / "whisper-dictate"
        assert paths.log_dir == tmp_path / "state" / "whisper-dictate" / "logs"

    def test_explicit_construction_overrides_defaults(self, tmp_path):
        """Explicit fields win over env — this is how a composition root (S2) will pass paths."""
        paths = AppPaths(data_home=tmp_path / "d", log_dir=tmp_path / "l")
        assert paths.data_home == tmp_path / "d"
        assert paths.log_dir == tmp_path / "l"
        assert paths.log_file == tmp_path / "l" / "whisper-dictate.log"
        assert paths.backup_dir == tmp_path / "d" / "backups"


class TestAppPathsResolvers:
    """Effective database/recordings resolvers: explicit DatabaseConfig override wins."""

    def test_database_path_default_under_data_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        paths = AppPaths()
        assert paths.database_path() == paths.data_home / "whisper-dictate.db"

    def test_database_path_explicit_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        override = tmp_path / "elsewhere" / "custom.db"
        paths = AppPaths()
        assert paths.database_path(DatabaseConfig(path=override)) == override

    def test_database_path_none_config_uses_default(self, monkeypatch, tmp_path):
        """Passing None resolves the XDG default (same as no argument)."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        paths = AppPaths()
        assert paths.database_path(None) == paths.data_home / "whisper-dictate.db"

    def test_recordings_dir_default_under_data_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        paths = AppPaths()
        assert paths.recordings_dir() == paths.data_home / "recordings"

    def test_recordings_dir_explicit_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        override = tmp_path / "elsewhere" / "recordings"
        paths = AppPaths()
        assert paths.recordings_dir(DatabaseConfig(recordings_path=override)) == override

    def test_database_config_getters_delegate_to_app_paths(self, monkeypatch, tmp_path):
        """DatabaseConfig.get_*_path() methods resolve through AppPaths (no duplicated XDG logic)."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        db_config = DatabaseConfig()
        assert db_config.get_database_path() == AppPaths().database_path(db_config)
        assert db_config.get_recordings_path() == AppPaths().recordings_dir(db_config)
        assert db_config.get_database_path() == tmp_path / "whisper-dictate" / "whisper-dictate.db"
        assert db_config.get_recordings_path() == tmp_path / "whisper-dictate" / "recordings"


class TestAppPathsFrozen:
    """AppPaths is immutable once constructed."""

    def test_frozen_model_rejects_mutation(self):
        paths = AppPaths()
        with pytest.raises(ValidationError):
            paths.data_home = Path("/somewhere/else")


class TestAppConfigPathsProperty:
    """AppConfig.paths re-reads the environment on every access."""

    def test_paths_reflect_env_at_access_time(self, clean_xdg_env, monkeypatch, tmp_path):
        """A caller (or test) may change XDG_* after the config was built."""
        config = AppConfig()
        assert config.paths.log_dir == Path.home() / ".local" / "state" / "whisper-dictate" / "logs"

        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        assert config.paths.log_dir == tmp_path / "state" / "whisper-dictate" / "logs"

    def test_paths_is_fresh_instance_per_access(self):
        """Each access returns a new AppPaths, never a cached snapshot."""
        config = AppConfig()
        assert config.paths is not config.paths

    def test_paths_sees_config_independent_of_database_override(self, monkeypatch, tmp_path):
        """AppConfig.paths exposes defaults; DatabaseConfig overrides still win via resolvers."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        config = AppConfig(database=DatabaseConfig(path=tmp_path / "custom.db"))
        assert config.paths.data_home == tmp_path / "xdg" / "whisper-dictate"
        assert config.database.get_database_path() == tmp_path / "custom.db"


class TestSharedLegacyPaths:
    """The legacy dotfiles must be identical everywhere they are referenced."""

    def test_toggle_and_migration_share_exact_app_paths_constants(self):
        """whisper_dictate.toggle's runtime files ARE migration's source files (single source of truth)."""
        from whisper_dictate import migration, toggle

        paths = AppPaths()
        assert toggle.STATE_FILE == migration.LEGACY_STATE_FILE == paths.legacy_state_file
        assert toggle.PID_FILE == migration.LEGACY_PID_FILE == paths.legacy_pid_file
        assert toggle.AUDIO_FILE == migration.LEGACY_AUDIO_FILE == paths.legacy_audio_file
