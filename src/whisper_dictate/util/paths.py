"""Pure audio path logic for whisper-dictate.

Owns every pure path computation for the recordings tree: date-based
directory derivation (YYYY/MM/DD), unique filename generation (timestamp +
random suffix), storage path composition, and containment validation of
stored paths against the recordings root. It also hosts the single
definition of the audio path exception family (``AudioPathError`` /
``NoAudioFileError`` / ``UnsafeAudioPathError``) so tests and consumers can
assert on one class identity.

WHY THIS EXISTS (roadmap S3 slice 2): this logic was hoisted out of
``audio_storage.py`` so pure path computation no longer lives inside the
I/O manager. The module performs no file I/O (``Path.resolve()`` during
containment validation is path logic, not access) and imports nothing from
``whisper_dictate``, which breaks the database<->audio import cycle and
lets the storage layer depend on it — never the reverse.
"""

import logging
import random
import string
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Length of random suffix for unique filenames
RANDOM_SUFFIX_LENGTH = 8


class AudioPathError(Exception):
    """Base error for audio path resolution failures."""


class NoAudioFileError(AudioPathError):
    """The recording has no audio file stored (empty file_path sentinel)."""


class UnsafeAudioPathError(AudioPathError):
    """A stored path resolves outside the recordings root and is never accessed.

    Raised for absolute paths outside the recordings directory, ``..`` traversal,
    and symlinks that escape the root. Files outside the root must never be read
    or unlinked based on database contents.
    """


def _generate_random_suffix(length: int = RANDOM_SUFFIX_LENGTH) -> str:
    """Generate a random alphanumeric suffix for unique filenames.

    Args:
        length: Length of the random suffix

    Returns:
        str: Random alphanumeric string
    """
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _generate_unique_filename(timestamp: datetime | None = None, suffix: str = "wav") -> str:
    """Generate a unique filename with timestamp and random suffix.

    Args:
        timestamp: Datetime for the filename (defaults to now)
        suffix: File extension (without dot)

    Returns:
        str: Unique filename in format YYYYMMDD_HHMMSS_random.wav
    """
    if timestamp is None:
        timestamp = datetime.now()

    date_part = timestamp.strftime("%Y%m%d_%H%M%S")
    random_part = _generate_random_suffix()

    return f"{date_part}_{random_part}.{suffix}"


def _get_date_based_path(base_path: Path, timestamp: datetime | None = None) -> Path:
    """Get the date-based directory path for a recording.

    Creates directory structure: base_path/YYYY/MM/DD/

    Args:
        base_path: Base recordings directory
        timestamp: Datetime for the path (defaults to now)

    Returns:
        Path: Full path to the date-based directory
    """
    if timestamp is None:
        timestamp = datetime.now()

    return base_path / f"{timestamp.year:04d}" / f"{timestamp.month:02d}" / f"{timestamp.day:02d}"


class AudioPathResolver:
    """Pure resolver for paths inside the recordings tree.

    RESPONSIBILITY: Compute and validate audio file paths (no I/O).
    BOUNDARIES:
    - DOES: Date-based directory derivation, unique filename generation,
      storage path composition, containment validation of stored paths
    - DOES NOT: Create directories, read/write/delete files, or touch the
      database (those remain in ``storage.audio_storage.AudioStorage``)

    The recordings root is injected explicitly; the resolver never consults
    configuration or globals itself, so callers keep a single path source of
    truth and the storage layer receives it as a constructor dependency.
    """

    def __init__(self, recordings_path: Path) -> None:
        """Initialize the resolver with the recordings root.

        Args:
            recordings_path: Base recordings directory all computations are
                relative to (e.g. ``DatabaseConfig.get_recordings_path()``)
        """
        self._recordings_path = recordings_path

    @property
    def recordings_path(self) -> Path:
        """Get the base recordings directory path.

        Returns:
            Path: Full path to recordings directory
        """
        return self._recordings_path

    def generate_random_suffix(self, length: int = RANDOM_SUFFIX_LENGTH) -> str:
        """Generate a random alphanumeric suffix for unique filenames.

        Args:
            length: Length of the random suffix

        Returns:
            str: Random alphanumeric string
        """
        return _generate_random_suffix(length)

    def generate_unique_filename(self, timestamp: datetime | None = None, suffix: str = "wav") -> str:
        """Generate a unique filename with timestamp and random suffix.

        Args:
            timestamp: Datetime for the filename (defaults to now)
            suffix: File extension (without dot)

        Returns:
            str: Unique filename in format YYYYMMDD_HHMMSS_random.wav
        """
        return _generate_unique_filename(timestamp, suffix)

    def get_date_directory(self, timestamp: datetime | None = None) -> Path:
        """Get the date-based directory path for a recording.

        Computes the directory structure: recordings_path/YYYY/MM/DD/

        Args:
            timestamp: Datetime for the path (defaults to now)

        Returns:
            Path: Full path to the date-based directory
        """
        return _get_date_based_path(self._recordings_path, timestamp)

    def generate_storage_path(self, timestamp: datetime | None = None, suffix: str = "wav") -> tuple[Path, str]:
        """Generate a unique storage path for a new recording.

        Pure computation only: the returned directory is NOT created; callers
        (``AudioStorage``) own all directory creation.

        Args:
            timestamp: Datetime for the filename (defaults to now)
            suffix: File extension (without dot)

        Returns:
            tuple[Path, str]: Full file path and the filename
        """
        # Get date-based directory
        directory = _get_date_based_path(self._recordings_path, timestamp)

        # Generate unique filename
        filename = _generate_unique_filename(timestamp, suffix)

        # Return full path
        return directory / filename, filename

    def resolve_contained(self, relative_path: str) -> Path:
        """Resolve a stored path against the recordings root, enforcing containment.

        Empty paths are the explicit "no file" sentinel. Absolute paths and
        ``..`` traversal are accepted only when they resolve inside the
        recordings root (legacy absolute in-root paths keep working); anything
        else is rejected and never accessed.

        Args:
            relative_path: Stored path (relative to the recordings root, or a
                legacy absolute path that resolves inside the root)

        Returns:
            Path: Fully resolved path inside the recordings root

        Raises:
            NoAudioFileError: If the stored path is empty (no file stored)
            UnsafeAudioPathError: If the path escapes the recordings root
        """
        if not relative_path or not relative_path.strip():
            raise NoAudioFileError("Recording has no audio file stored (empty file path)")

        root = self._recordings_path.resolve()
        candidate = (self._recordings_path / relative_path).resolve()

        if candidate == root or not candidate.is_relative_to(root):
            logger.warning(
                f"Refusing unsafe audio path {relative_path!r}: resolves to "
                f"{candidate}, which is outside the recordings root {root}"
            )
            raise UnsafeAudioPathError(
                f"Stored path {relative_path!r} escapes the recordings root ({root}); the file will not be accessed."
            )

        return candidate
