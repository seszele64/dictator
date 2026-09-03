"""Clipboard integration for Arch Linux with strong typing."""

import logging
import subprocess

logger = logging.getLogger(__name__)


class ClipboardManager:
    """WHY THIS EXISTS: Clipboard operations need to be abstracted to handle
    different Linux environments and provide consistent error handling.

    RESPONSIBILITY: Copy text to system clipboard on Linux.
    BOUNDARIES:
    - DOES: Copy text to clipboard using available tools
    - DOES NOT: Handle text generation or user interface

    RELATIONSHIPS:
    - USED BY: DictationService for clipboard operations
    """

    def __init__(self) -> None:
        """Initialize clipboard manager and detect available tools."""
        self.available_tools = self._detect_clipboard_tools()

    def _detect_clipboard_tools(self) -> list[str]:
        """WHY THIS EXISTS: Different Linux distributions have different
        clipboard tools, and we need to detect what's available.

        RESPONSIBILITY: Detect available clipboard tools on the system.
        BOUNDARIES:
        - DOES: Check for clipboard tools in PATH
        - DOES NOT: Install or configure tools

        Returns:
            list[str]: Names of available clipboard tools
        """
        tools = ["xclip", "xsel", "wl-copy"]
        available = []

        for tool in tools:
            try:
                subprocess.run(["which", tool], check=True, capture_output=True, timeout=2)
                available.append(tool)
                logger.debug(f"Found clipboard tool: {tool}")
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                continue

        return available

    def copy_to_clipboard(self, text: str) -> bool:
        """WHY THIS EXISTS: Text needs to be copied to clipboard reliably
        across different Linux environments.

        RESPONSIBILITY: Copy text to system clipboard using available tools.
        BOUNDARIES:
        - DOES: Copy text to clipboard
        - DOES NOT: Handle text generation or validation

        Args:
            text: Text to copy to clipboard

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.available_tools:
            logger.error("No clipboard tools available")
            return False

        for tool in self.available_tools:
            try:
                if tool == "xclip":
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True, timeout=5
                    )
                elif tool == "xsel":
                    subprocess.run(
                        ["xsel", "--clipboard", "--input"], input=text.encode("utf-8"), check=True, timeout=5
                    )
                elif tool == "wl-copy":
                    subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=True, timeout=5)

                logger.info(f"Text copied to clipboard using {tool}")
                return True

            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                logger.warning(f"Failed to copy with {tool}: {e}")
                continue

        logger.error("All clipboard tools failed")
        return False
