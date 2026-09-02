"""CLI tests exercising the REAL bootstrap() validation path.

tests/conftest.py patches whisper_dictate.cli.bootstrap at session scope
(autouse) to keep the other CLI tests hermetic. These tests need the real
provider/key validation, so the real_bootstrap fixture re-patches
whisper_dictate.cli.bootstrap with the actual function.
"""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from whisper_dictate import __version__
from whisper_dictate.app import bootstrap
from whisper_dictate.cli import cli


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def real_load_config():
    """Swap the session-scoped bootstrap mock for the real function.

    The session autouse fixture in tests/conftest.py mocks
    whisper_dictate.cli.bootstrap to keep other CLI tests hermetic; these
    tests must exercise the real env-var resolution and key validation.
    """
    with patch("whisper_dictate.cli.bootstrap", bootstrap):
        yield


@pytest.fixture
def clean_provider_env(monkeypatch, tmp_path):
    """Keyless provider environment with XDG data redirected to a temp dir.

    Removes all API-key env vars (conftest sets OPENAI_API_KEY at session
    scope) and sets WHISPER_PROVIDER=local so every command must work with
    no key configured.
    """
    for var in (
        "WHISPER_PROVIDER",
        "WHISPER_API_KEY",
        "WHISPER_BASE_URL",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "TOGETHER_API_KEY",
        "DEEPINFRA_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WHISPER_PROVIDER", "local")
    # Redirect XDG data (database, recordings) and state (logs) away from the
    # real home dir
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return monkeypatch


class TestKeylessNonTranscriptionCommands:
    """Database-only commands must run without any API key configured."""

    def test_migrate_status_runs_without_api_key(self, cli_runner, real_load_config, clean_provider_env):
        """Regression: WHISPER_PROVIDER=local with no key crashed on every command."""
        result = cli_runner.invoke(cli, ["migrate", "--status"])

        assert result.exit_code == 0, result.output
        assert "API key not found" not in result.output

    def test_logs_list_runs_without_api_key(self, cli_runner, real_load_config, clean_provider_env):
        result = cli_runner.invoke(cli, ["logs", "list"])

        assert result.exit_code == 0, result.output
        assert "API key not found" not in result.output


class TestDictateKeylessLocal:
    """dictate-path validation must accept a keyless local provider."""

    def test_dictate_keyless_local_passes_validation(
        self, cli_runner, real_load_config, clean_provider_env
    ):
        """A keyless local provider must get past lazy key validation.

        Unit level: DictationService is mocked so no recording happens; we
        only verify the command proceeds past the key check without the
        'Configuration error' path.
        """
        with patch("whisper_dictate.cli.DictationService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_result = mock_service.dictate.return_value
            mock_result.text = "hello from local"
            mock_result.language = "en"

            result = cli_runner.invoke(cli, ["dictate"])

            assert result.exit_code == 0, result.output
            assert "API key not found" not in result.output
            assert "hello from local" in result.output
            mock_service_cls.assert_called_once()

    def test_dictate_openai_without_key_fails_friendly(
        self, cli_runner, real_load_config, clean_provider_env
    ):
        """A keyless openai provider must fail with the friendly error, not a traceback."""
        clean_provider_env.setenv("WHISPER_PROVIDER", "openai")

        result = cli_runner.invoke(cli, ["dictate"])

        assert result.exit_code == 1
        # Failure banner carries the version (P1): bug reports from this path
        # are self-identifying without the reporter running --version.
        assert (
            f"Configuration error (whisper-dictate v{__version__}): "
            "API key not found" in result.output
        )
