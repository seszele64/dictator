"""Config-wiring regression tests.

Every persistence path used to construct DatabaseConfig() defaults instead of
the loaded configuration, silently ignoring user-configured database paths,
recordings paths, free-space thresholds and log retention. These tests drive
CliRunner with a custom AppConfig and verify the configured values are
actually honored end-to-end.
"""

from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from whisper_dictate.cli import cli
from whisper_dictate.config import (
    AppConfig,
    AudioConfig,
    DatabaseConfig,
    WhisperConfig,
)
from whisper_dictate.database import Database
from whisper_dictate.dictation import DictationService
from whisper_dictate.transcription import TranscriptionResult


@pytest.fixture
def custom_config(tmp_path) -> AppConfig:
    """AppConfig with custom database/recordings paths and thresholds."""
    return AppConfig(
        database=DatabaseConfig(
            path=tmp_path / "custom-data" / "custom.db",
            recordings_path=tmp_path / "custom-recordings",
            min_free_space_mb=999999,  # impossible threshold, for the disk-check spy
            log_retention_days=7,
        ),
        audio=AudioConfig(mp3_enabled=False, duration=1.0),
        openai=WhisperConfig(api_key="test-api-key"),
    )


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def invoke_with_config(cli_runner, config, args):
    """Invoke the CLI with a real custom config overriding the session mock."""
    with (
        patch("whisper_dictate.cli.bootstrap", return_value=config),
        patch("whisper_dictate.cli.setup_logging", return_value=None),
    ):
        return cli_runner.invoke(cli, args)


class TestConfiguredDatabasePath:
    def test_history_list_creates_db_at_custom_path(self, cli_runner, custom_config, tmp_path):
        result = invoke_with_config(cli_runner, custom_config, ["history", "list"])

        assert result.exit_code == 0, result.output
        assert "No transcriptions found" in result.output
        # The database was created at the configured path, not the XDG default
        db_path = custom_config.database.get_database_path()
        assert db_path == tmp_path / "custom-data" / "custom.db"
        assert db_path.exists()
        probe = Database(custom_config.database)
        try:
            tables = {row[0] for row in probe.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            probe.close()
        assert {"recordings", "transcripts", "schema_versions"} <= tables


class TestConfiguredDiskCheck:
    def test_dictate_disk_check_uses_configured_values(self, cli_runner, custom_config, tmp_path):
        recordings_path = tmp_path / "custom-recordings"
        success = TranscriptionResult(text="wired", language="en")

        with (
            patch("whisper_dictate.cli.check_disk_space", return_value=(True, 500000)) as mock_check,
            patch.object(DictationService, "dictate", return_value=success),
        ):
            result = invoke_with_config(cli_runner, custom_config, ["dictate"])

        assert result.exit_code == 0, result.output
        mock_check.assert_called_once_with(recordings_path, 999999)
        assert "Transcription: wired" in result.output


class TestConfiguredLogRetention:
    def test_logs_cleanup_uses_configured_retention(self, cli_runner, custom_config):
        db = Mock()
        db.cleanup_old_logs = Mock(return_value=3)
        db.close = Mock()

        with (
            patch("whisper_dictate.cli.bootstrap", return_value=custom_config),
            patch("whisper_dictate.cli.setup_logging", return_value=None),
            patch("whisper_dictate.cli_helpers.Database", return_value=db),
        ):
            result = cli_runner.invoke(cli, ["logs", "cleanup"])

        assert result.exit_code == 0, result.output
        db.cleanup_old_logs.assert_called_once_with(7)
        assert "older than 7 days" in result.output


class TestConfiguredRecordingsCleanup:
    def test_audio_cleanup_removes_orphans_in_configured_dir(self, cli_runner, custom_config, tmp_path):
        recordings_root = tmp_path / "custom-recordings"
        orphan_dir = recordings_root / "2026/08/31"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "orphan.wav"
        orphan.write_bytes(b"orphan audio")

        result = invoke_with_config(cli_runner, custom_config, ["audio", "cleanup", "--confirm"])

        assert result.exit_code == 0, result.output
        assert "orphan.wav" in result.output  # listed before deletion
        assert "Deleted 1 orphaned file(s)" in result.output
        assert not orphan.exists()
