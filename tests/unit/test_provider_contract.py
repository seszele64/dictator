"""Unit tests for the transcription domain types (spec 008).

Pure dataclass/exception tests for `TranscriptionResult` and
`TranscriptionError` stay in `tests/unit/`. The provider seam contract tests
(ABC conformance, error wrapping, parameter forwarding, factory selection)
live in `tests/contract/test_openai_compatible.py`.
"""

import pytest

from whisper_dictate.transcription import TranscriptionError, TranscriptionResult


class TestTranscriptionResult:
    """Tests for the TranscriptionResult dataclass."""

    def test_init_defaults(self):
        """Defaults are set when only text is provided."""
        result = TranscriptionResult("hello")
        assert result.text == "hello"
        assert result.language is None
        assert result.duration is None
        assert result.provider is None
        assert result.silence_detected is False

    def test_init_all_fields(self):
        """All fields are stored when provided."""
        result = TranscriptionResult(
            text="hello",
            language="en",
            duration=3.5,
            provider="openai",
            silence_detected=True,
        )
        assert result.text == "hello"
        assert result.language == "en"
        assert result.duration == 3.5
        assert result.provider == "openai"
        assert result.silence_detected is True

    def test_str_returns_text(self):
        """str() returns the transcription text."""
        assert str(TranscriptionResult("hello")) == "hello"

    def test_repr_normal(self):
        """repr includes text (with truncation marker) and language."""
        result = TranscriptionResult("hello world", language="en")
        assert "TranscriptionResult(" in repr(result)
        assert "hello world" in repr(result)
        assert "..." in repr(result)
        assert "language=en" in repr(result)

    def test_repr_silence_detected(self):
        """repr reports silence_detected with empty text."""
        result = TranscriptionResult("", silence_detected=True, provider="openai")
        assert "silence_detected=True" in repr(result)
        assert "text=''" in repr(result)

    def test_repr_long_text_truncated(self):
        """repr truncates text longer than 50 characters."""
        long_text = "a" * 100
        result = TranscriptionResult(long_text)
        assert long_text[:50] in repr(result)
        assert "..." in repr(result)
        assert long_text not in repr(result)


class TestTranscriptionError:
    """Tests for the TranscriptionError exception."""

    def test_init_with_message(self):
        """Message is stored as the exception argument."""
        err = TranscriptionError("error msg")
        assert err.args[0] == "error msg"
        assert err.provider is None

    def test_init_with_provider(self):
        """Provider name is stored on the exception."""
        err = TranscriptionError("msg", provider="openai")
        assert err.provider == "openai"

    def test_is_exception(self):
        """TranscriptionError is an Exception subclass."""
        assert isinstance(TranscriptionError("msg"), Exception)

    def test_raises_and_catches(self):
        """TranscriptionError can be raised and caught by message."""
        with pytest.raises(TranscriptionError, match="msg"):
            raise TranscriptionError("msg")
