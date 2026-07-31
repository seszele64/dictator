"""Tests for clipboard functionality."""

from unittest.mock import Mock, patch

from whisper_dictate.clipboard import ClipboardManager


class TestClipboardManager:
    """Test the ClipboardManager class."""

    def test_init_no_tools_available(self):
        """Test initialization when no clipboard tools are available."""
        from subprocess import CalledProcessError

        with patch('subprocess.run') as mock_run:
            # Simulate "which" command failing for all tools
            mock_run.side_effect = [
                CalledProcessError(1, "which"),  # xclip not found
                CalledProcessError(1, "which"),  # xsel not found
                CalledProcessError(1, "which"),  # wl-copy not found
            ]

            manager = ClipboardManager()
            assert manager.available_tools == []

    def test_init_with_xclip_available(self):
        """Test initialization when xclip is available."""
        from subprocess import CalledProcessError

        with patch('subprocess.run') as mock_run:
            # Simulate xclip being available
            mock_run.side_effect = [
                Mock(returncode=0),  # xclip found
                CalledProcessError(1, "which"),  # xsel not found
                CalledProcessError(1, "which"),  # wl-copy not found
            ]

            manager = ClipboardManager()
            assert manager.available_tools == ["xclip"]

    def test_init_with_multiple_tools_available(self):
        """Test initialization with multiple clipboard tools available."""
        with patch('subprocess.run') as mock_run:
            # Simulate multiple tools being available
            mock_run.side_effect = [
                Mock(returncode=0),  # xclip found
                Mock(returncode=0),  # xsel found
                Mock(returncode=0),  # wl-copy found
            ]

            manager = ClipboardManager()
            assert manager.available_tools == ["xclip", "xsel", "wl-copy"]

    def test_copy_to_clipboard_no_tools(self):
        """Test copying when no clipboard tools are available."""
        manager = ClipboardManager()
        manager.available_tools = []

        result = manager.copy_to_clipboard("test text")
        assert result is False

    def test_copy_to_clipboard_xclip_success(self):
        """Test successful copy using xclip."""
        manager = ClipboardManager()
        manager.available_tools = ["xclip"]

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = manager.copy_to_clipboard("test text")
            assert result is True

            mock_run.assert_called_once_with(
                ["xclip", "-selection", "clipboard"],
                input=b"test text",
                check=True,
                timeout=5
            )

    def test_copy_to_clipboard_xsel_success(self):
        """Test successful copy using xsel."""
        manager = ClipboardManager()
        manager.available_tools = ["xsel"]

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = manager.copy_to_clipboard("test text")
            assert result is True

            mock_run.assert_called_once_with(
                ["xsel", "--clipboard", "--input"],
                input=b"test text",
                check=True,
                timeout=5
            )

    def test_copy_to_clipboard_wl_copy_success(self):
        """Test successful copy using wl-copy."""
        manager = ClipboardManager()
        manager.available_tools = ["wl-copy"]

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = manager.copy_to_clipboard("test text")
            assert result is True

            mock_run.assert_called_once_with(
                ["wl-copy"],
                input=b"test text",
                check=True,
                timeout=5
            )

    def test_copy_to_clipboard_fallback_behavior(self):
        """Test fallback behavior when first tool fails."""
        from subprocess import CalledProcessError

        manager = ClipboardManager()
        manager.available_tools = ["xclip", "xsel"]

        with patch('subprocess.run') as mock_run:
            # First call fails, second succeeds
            mock_run.side_effect = [
                CalledProcessError(1, "xclip"),  # xclip fails
                Mock(returncode=0),  # xsel succeeds
            ]

            result = manager.copy_to_clipboard("test text")
            assert result is True

            # Should have tried both tools
            assert mock_run.call_count == 2

    def test_copy_to_clipboard_all_tools_fail(self):
        """Test when all available tools fail."""
        from subprocess import CalledProcessError

        manager = ClipboardManager()
        manager.available_tools = ["xclip", "xsel"]

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                CalledProcessError(1, "xclip"),
                CalledProcessError(1, "xsel"),
            ]

            result = manager.copy_to_clipboard("test text")
            assert result is False

    def test_copy_to_clipboard_timeout_error(self):
        """Test handling of subprocess timeout."""
        manager = ClipboardManager()
        manager.available_tools = ["xclip"]

        with patch('subprocess.run') as mock_run:
            from subprocess import TimeoutExpired
            mock_run.side_effect = TimeoutExpired("xclip", 5)

            result = manager.copy_to_clipboard("test text")
            assert result is False

    def test_copy_to_clipboard_unicode_text(self):
        """Test copying unicode text."""
        manager = ClipboardManager()
        manager.available_tools = ["xclip"]

        unicode_text = "Hello 世界 🌍"

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = manager.copy_to_clipboard(unicode_text)
            assert result is True

            mock_run.assert_called_once_with(
                ["xclip", "-selection", "clipboard"],
                input=unicode_text.encode("utf-8"),
                check=True,
                timeout=5
            )

    def test_copy_to_clipboard_empty_text(self):
        """Test copying empty text."""
        manager = ClipboardManager()
        manager.available_tools = ["xclip"]

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)

            result = manager.copy_to_clipboard("")
            assert result is True

            mock_run.assert_called_once_with(
                ["xclip", "-selection", "clipboard"],
                input=b"",
                check=True,
                timeout=5
            )
