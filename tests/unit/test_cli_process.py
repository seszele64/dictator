"""Unit tests for the `whisper-dictate process` command (Group 6).

Covers the fixed guard order (recording -> transcript -> config -> prompt),
prompt-source outcomes, the success path ordering, failure isolation, clipboard
failure handling, and the additive `history show` processed block.

All external seams are mocked: the chat client, the launcher, the clipboard,
notifications, and the database. No network, subprocess, or real SQLite.
"""

from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from whisper_dictate.cli import cli
from whisper_dictate.config import AppConfig, DatabaseConfig, PostProcessConfig, WhisperConfig
from whisper_dictate.notifications import CLIPBOARD_FAILURE_LINE
from whisper_dictate.post_processor import PostProcessError
from whisper_dictate.prompting import PromptUnavailableError

TRANSCRIPT = {
    "id": 7,
    "recording_id": 1,
    "text": "um so hello there",
    "language": "en",
    "model_used": "whisper-1",
    "confidence": None,
    "timestamp": "2026-11-07 09:00:00",
    "created_at": "2026-11-07 09:00:00",
    "updated_at": "2026-11-07 09:00:00",
    "processed_text": None,
    "processed_prompt": None,
    "processed_model": None,
    "processed_at": None,
}


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def process_config():
    """A real AppConfig with a valid chat block (local provider, keyless)."""
    return AppConfig(
        database=DatabaseConfig(),
        openai=WhisperConfig(api_key="test-api-key", model="whisper-1"),
        post_process=PostProcessConfig(provider="local", model="gpt-4o-mini", prompt=""),
    )


@pytest.fixture
def mock_db():
    db = Mock()
    db.initialize = Mock()
    db.close = Mock()
    db.get_latest_processable_transcript = Mock(return_value=dict(TRANSCRIPT))
    db.set_processed_transcript = Mock(return_value=True)
    return db


def _invoke(cli_runner, config, db, args, *, is_recording=False, prompt="Clean up", acquire_error=None):
    """Invoke `process` with every external seam patched.

    Returns (result, mocks-dict) so tests can assert on the seams.
    """
    with (
        patch("whisper_dictate.cli.bootstrap", lambda *a, **k: config),
        patch("whisper_dictate.cli_helpers.Database", return_value=db),
        patch("whisper_dictate.toggle.is_recording", return_value=is_recording) as m_rec,
        patch("whisper_dictate.config.validate_post_process_config") as m_validate,
        patch("whisper_dictate.prompting.acquire_prompt") as m_acquire,
        patch("whisper_dictate.post_processor.create_post_processor") as m_create,
        patch("whisper_dictate.clipboard.ClipboardManager") as m_clipboard_cls,
        patch("whisper_dictate.notifications.notify_processing_skipped") as m_skipped,
        patch("whisper_dictate.notifications.notify_error") as m_error,
        patch("whisper_dictate.notifications.notify_processed") as m_processed,
    ):
        if acquire_error is not None:
            m_acquire.side_effect = acquire_error
        else:
            m_acquire.return_value = prompt

        processor = Mock()
        processor.process.return_value = "Clean output"
        m_create.return_value = processor

        clipboard = Mock()
        clipboard.copy_to_clipboard.return_value = True
        m_clipboard_cls.return_value = clipboard

        result = cli_runner.invoke(cli, ["process", *args])

    return result, {
        "is_recording": m_rec,
        "validate": m_validate,
        "acquire": m_acquire,
        "create": m_create,
        "processor": processor,
        "clipboard": clipboard,
        "clipboard_cls": m_clipboard_cls,
        "skipped": m_skipped,
        "error": m_error,
        "processed": m_processed,
    }


class TestProcessHelp:
    def test_help_documents_prompt_and_no_clipboard(self, cli_runner):
        result = cli_runner.invoke(cli, ["process", "--help"])
        assert result.exit_code == 0
        assert "--prompt" in result.output
        assert "--no-clipboard" in result.output


class TestRecordingGuard:
    def test_recording_refuses_before_any_side_effect(self, cli_runner, process_config, mock_db):
        result, mocks = _invoke(cli_runner, process_config, mock_db, [], is_recording=True)

        assert result.exit_code == 1
        mocks["skipped"].assert_called_once_with("Stop recording first.")
        mock_db.get_latest_processable_transcript.assert_not_called()
        mocks["validate"].assert_not_called()
        mocks["acquire"].assert_not_called()
        mocks["create"].assert_not_called()
        mocks["clipboard_cls"].assert_not_called()
        mock_db.set_processed_transcript.assert_not_called()
        mocks["processed"].assert_not_called()


class TestEmptyHistoryGuard:
    def test_no_transcript_notifies_and_exits(self, cli_runner, process_config, mock_db):
        mock_db.get_latest_processable_transcript.return_value = None

        result, mocks = _invoke(cli_runner, process_config, mock_db, [])

        assert result.exit_code == 1
        mocks["skipped"].assert_called_once_with("No transcript to process.")
        mocks["validate"].assert_not_called()
        mocks["create"].assert_not_called()
        mock_db.set_processed_transcript.assert_not_called()


class TestConfigValidation:
    def test_validation_error_notifies_and_exits_before_prompt(self, cli_runner, process_config, mock_db):
        with (
            patch("whisper_dictate.cli.bootstrap", lambda *a, **k: process_config),
            patch("whisper_dictate.cli_helpers.Database", return_value=mock_db),
            patch("whisper_dictate.toggle.is_recording", return_value=False),
            patch(
                "whisper_dictate.config.validate_post_process_config",
                side_effect=ValueError("POST_PROCESS_MODEL is required but not set."),
            ),
            patch("whisper_dictate.prompting.acquire_prompt") as m_acquire,
            patch("whisper_dictate.post_processor.create_post_processor") as m_create,
            patch("whisper_dictate.notifications.notify_error") as m_error,
        ):
            result = cli_runner.invoke(cli, ["process"])

        assert result.exit_code == 1
        m_error.assert_called_once()
        assert "POST_PROCESS_MODEL" in m_error.call_args.args[0]
        m_acquire.assert_not_called()
        m_create.assert_not_called()
        mock_db.set_processed_transcript.assert_not_called()


class TestPromptAcquisition:
    def test_prompt_none_is_silent_exit_zero(self, cli_runner, process_config, mock_db):
        result, mocks = _invoke(cli_runner, process_config, mock_db, [], prompt=None)

        assert result.exit_code == 0
        mocks["skipped"].assert_not_called()
        mocks["error"].assert_not_called()
        mocks["processed"].assert_not_called()
        mocks["create"].assert_not_called()
        mock_db.set_processed_transcript.assert_not_called()

    def test_prompt_unavailable_notifies_and_exits_one(self, cli_runner, process_config, mock_db):
        result, mocks = _invoke(
            cli_runner,
            process_config,
            mock_db,
            [],
            acquire_error=PromptUnavailableError("No prompt source available"),
        )

        assert result.exit_code == 1
        mocks["error"].assert_called_once()
        mocks["create"].assert_not_called()
        mock_db.set_processed_transcript.assert_not_called()

    def test_explicit_prompt_is_passed_through(self, cli_runner, process_config, mock_db):
        _, mocks = _invoke(cli_runner, process_config, mock_db, ["--prompt", "Summarize this"])

        mocks["acquire"].assert_called_once_with("Summarize this", "")


class TestSuccessPath:
    def test_order_and_values(self, cli_runner, process_config, mock_db):
        result, mocks = _invoke(cli_runner, process_config, mock_db, ["--prompt", "Clean up"])

        assert result.exit_code == 0
        # DB write with exact prompt and stripped model.
        mock_db.set_processed_transcript.assert_called_once_with(7, "Clean output", "Clean up", "gpt-4o-mini")
        # Clipboard got the stripped output.
        mocks["clipboard"].copy_to_clipboard.assert_called_once_with("Clean output")
        # One notification with the preview and copied=True.
        mocks["processed"].assert_called_once_with("Clean output", clipboard_copied=True)
        # The processor received the raw transcript and the prompt.
        mocks["processor"].process.assert_called_once_with("um so hello there", "Clean up")

    def test_padded_model_is_stripped_for_db(self, cli_runner, mock_db):
        config = AppConfig(
            database=DatabaseConfig(),
            openai=WhisperConfig(api_key="test-api-key", model="whisper-1"),
            post_process=PostProcessConfig(provider="local", model="  gpt-4o-mini  "),
        )
        result, _ = _invoke(cli_runner, config, mock_db, ["--prompt", "x"])

        assert result.exit_code == 0
        assert mock_db.set_processed_transcript.call_args.args[3] == "gpt-4o-mini"

    def test_no_clipboard_skips_copy_and_exits_zero(self, cli_runner, process_config, mock_db):
        result, mocks = _invoke(cli_runner, process_config, mock_db, ["--prompt", "x", "--no-clipboard"])

        assert result.exit_code == 0
        mocks["clipboard_cls"].assert_not_called()
        mocks["processed"].assert_called_once_with("Clean output", clipboard_copied=True)
        mock_db.set_processed_transcript.assert_called_once()


class TestFailureIsolation:
    def test_post_process_error_leaves_db_and_clipboard_untouched(self, cli_runner, process_config, mock_db):
        with (
            patch("whisper_dictate.cli.bootstrap", lambda *a, **k: process_config),
            patch("whisper_dictate.cli_helpers.Database", return_value=mock_db),
            patch("whisper_dictate.toggle.is_recording", return_value=False),
            patch("whisper_dictate.config.validate_post_process_config"),
            patch("whisper_dictate.prompting.acquire_prompt", return_value="Clean up"),
            patch("whisper_dictate.post_processor.create_post_processor") as m_create,
            patch("whisper_dictate.clipboard.ClipboardManager") as m_clipboard_cls,
            patch("whisper_dictate.notifications.notify_error") as m_error,
            patch("whisper_dictate.notifications.notify_processed") as m_processed,
        ):
            m_create.return_value.process.side_effect = PostProcessError("Chat provider error.")
            result = cli_runner.invoke(cli, ["process"])

        assert result.exit_code == 1
        m_error.assert_called_once_with("Chat provider error.")
        mock_db.set_processed_transcript.assert_not_called()
        m_clipboard_cls.assert_not_called()
        m_processed.assert_not_called()

    def test_oversized_transcript_is_same_failure_path(self, cli_runner, process_config, mock_db):
        with (
            patch("whisper_dictate.cli.bootstrap", lambda *a, **k: process_config),
            patch("whisper_dictate.cli_helpers.Database", return_value=mock_db),
            patch("whisper_dictate.toggle.is_recording", return_value=False),
            patch("whisper_dictate.config.validate_post_process_config"),
            patch("whisper_dictate.prompting.acquire_prompt", return_value="Clean up"),
            patch("whisper_dictate.post_processor.create_post_processor") as m_create,
            patch("whisper_dictate.clipboard.ClipboardManager") as m_clipboard_cls,
            patch("whisper_dictate.notifications.notify_error") as m_error,
        ):
            m_create.return_value.process.side_effect = PostProcessError(
                "Chat provider rejected the request. Check POST_PROCESS_MODEL and the transcript length."
            )
            result = cli_runner.invoke(cli, ["process"])

        assert result.exit_code == 1
        m_error.assert_called_once()
        mock_db.set_processed_transcript.assert_not_called()
        m_clipboard_cls.assert_not_called()


class TestClipboardFailure:
    def test_copy_failure_keeps_db_and_exits_one(self, cli_runner, process_config, mock_db):
        with (
            patch("whisper_dictate.cli.bootstrap", lambda *a, **k: process_config),
            patch("whisper_dictate.cli_helpers.Database", return_value=mock_db),
            patch("whisper_dictate.toggle.is_recording", return_value=False),
            patch("whisper_dictate.config.validate_post_process_config"),
            patch("whisper_dictate.prompting.acquire_prompt", return_value="Clean up"),
            patch("whisper_dictate.post_processor.create_post_processor") as m_create,
            patch("whisper_dictate.clipboard.ClipboardManager") as m_clipboard_cls,
            patch("whisper_dictate.notifications.notify_processed") as m_processed,
            patch("whisper_dictate.notifications.notify_error") as m_error,
        ):
            m_create.return_value.process.return_value = "Clean output"
            m_clipboard_cls.return_value.copy_to_clipboard.return_value = False
            result = cli_runner.invoke(cli, ["process"])

        assert result.exit_code == 1
        # Persistence happened BEFORE the failed copy and is kept.
        mock_db.set_processed_transcript.assert_called_once_with(7, "Clean output", "Clean up", "gpt-4o-mini")
        # Exactly one notification, with the failure flag.
        m_processed.assert_called_once_with("Clean output", clipboard_copied=False)
        m_error.assert_not_called()
        assert CLIPBOARD_FAILURE_LINE == "⚠️ Clipboard copy failed. Result saved to history."


class TestHistoryShowProcessedBlock:
    """Group 6: additive processed block in `history show`."""

    def _row(self, **overrides):
        row = {
            "id": 1,
            "text": "raw transcript",
            "timestamp": "2026-11-07 09:00:00",
            "duration": 2.0,
            "language": "en",
            "model_used": "whisper-1",
            "confidence": None,
            "file_path": "r.wav",
            "recording_id": 1,
            "updated_at": "2026-11-07 09:00:00",
            "processed_text": None,
            "processed_prompt": None,
            "processed_model": None,
            "processed_at": None,
        }
        row.update(overrides)
        return row

    def _invoke_show(self, cli_runner, row):
        db = Mock()
        db.initialize = Mock()
        db.close = Mock()
        db.get_transcription_with_recording = Mock(return_value=row)
        with (
            patch("whisper_dictate.cli_helpers.Database", return_value=db),
        ):
            return cli_runner.invoke(cli, ["history", "show", "1"])

    def test_fully_populated_row_shows_all_fields(self, cli_runner):
        row = self._row(
            processed_text="Hello there.",
            processed_prompt="Clean up",
            processed_model="gpt-4o-mini",
            processed_at="2026-11-07 10:00:00",
            updated_at="2026-11-07 09:00:00",
        )
        result = self._invoke_show(cli_runner, row)

        assert result.exit_code == 0
        assert "🧠 Processed" in result.output
        assert "Hello there." in result.output
        assert "🧾 Prompt: Clean up" in result.output
        assert "🤖 Processed with: gpt-4o-mini" in result.output
        assert "🕒 Processed at: 2026-11-07 10:00:00" in result.output
        # Raw transcript still shown above.
        assert "raw transcript" in result.output
        assert "stale" not in result.output

    def test_unprocessed_row_has_no_processed_block(self, cli_runner):
        result = self._invoke_show(cli_runner, self._row())

        assert result.exit_code == 0
        assert "🧠 Processed" not in result.output
        assert "🧾 Prompt:" not in result.output
        assert "🤖 Processed with:" not in result.output
        assert "🕒 Processed at:" not in result.output

    def test_empty_processed_text_has_no_block(self, cli_runner):
        result = self._invoke_show(cli_runner, self._row(processed_text="   "))

        assert "🧠 Processed" not in result.output

    def test_partial_metadata_renders_not_recorded(self, cli_runner):
        row = self._row(processed_text="Result only", processed_at="2026-11-07 10:00:00")
        result = self._invoke_show(cli_runner, row)

        assert "🧠 Processed" in result.output
        assert "🧾 Prompt: (not recorded)" in result.output
        assert "🤖 Processed with: (not recorded)" in result.output
        assert "🕒 Processed at: 2026-11-07 10:00:00" in result.output

    def test_edited_after_processing_shows_stale_warning(self, cli_runner):
        row = self._row(
            processed_text="Old result",
            processed_prompt="Clean",
            processed_model="gpt-4o-mini",
            processed_at="2026-11-07 10:00:00",
            updated_at="2026-11-07 11:00:00",
        )
        result = self._invoke_show(cli_runner, row)

        assert result.exit_code == 0
        assert "🧠 Processed" in result.output
        assert "Old result" in result.output
        assert "edited after this processing" in result.output
        assert "may be stale" in result.output

    def test_updated_at_equal_to_processed_at_is_not_stale(self, cli_runner):
        row = self._row(
            processed_text="Result",
            processed_at="2026-11-07 10:00:00",
            updated_at="2026-11-07 10:00:00",
        )
        result = self._invoke_show(cli_runner, row)

        assert "may be stale" not in result.output
