"""Audio storage management for whisper-dictate.

Provides audio file storage with:
- XDG Base Directory spec compliance (root resolved from configuration by
  the caller and injected via ``AudioPathResolver``)
- Date-based directory structure (YYYY/MM/DD)
- Unique filename generation (timestamp + random suffix)
- File save, retrieve, and cleanup operations
- Disk space checking for safe recording

Pure path computation lives in ``whisper_dictate.util.paths`` and is
injected as an ``AudioPathResolver``; this module performs the I/O.
Orphan scanning/cleanup lives in ``whisper_dictate.storage.orphan_scan``
(``OrphanScanner``); this module does not depend on the database.
"""

import contextlib
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from whisper_dictate.config import DatabaseConfig
from whisper_dictate.util.paths import (
    AudioPathError,
    AudioPathResolver,
    NoAudioFileError,
    UnsafeAudioPathError,
)

logger = logging.getLogger(__name__)

# Default minimum free space threshold in MB
DEFAULT_MIN_FREE_SPACE_MB = 100

# Prefix for staged (in-progress) audio files inside the destination directory.
# Files are staged under this name and atomically renamed into place, so the
# final path never contains a partial file. The orphan scan
# (``whisper_dictate.storage.orphan_scan``) skips files with this prefix.
STAGING_PREFIX = ".staging-"


@dataclass(frozen=True)
class StagedAudio:
    """A staged audio file awaiting atomic finalization into storage.

    Attributes:
        staged_path: Temporary copy of the audio inside the destination directory
        final_path: Final absolute path the file will occupy after finalization
        relative_path: Final path relative to the recordings root (stored in the DB)
    """

    staged_path: Path
    final_path: Path
    relative_path: str


def check_disk_space(path: Path, min_free_mb: int = DEFAULT_MIN_FREE_SPACE_MB) -> tuple[bool, int]:
    """Check available disk space on the filesystem containing the given path.

    Args:
        path: Path to check disk space for (directory or file)
        min_free_mb: Minimum free space required in MB (default: 100MB)

    Returns:
        Tuple[bool, int]: (has_space, available_mb) - True if enough space available,
                         and the available space in MB
    """
    try:
        # Get the disk statistics for the filesystem containing the path
        stat_result = os.statvfs(path)

        # Calculate available space in bytes
        # f_bavail is the number of free blocks available to non-root users
        available_bytes = stat_result.f_bavail * stat_result.f_frsize

        # Convert to MB
        available_mb = available_bytes // (1024 * 1024)

        has_space = available_mb >= min_free_mb

        logger.debug(f"Disk space check for {path}: {available_mb}MB available, {min_free_mb}MB required")

        return has_space, available_mb

    except OSError as e:
        logger.warning(f"Failed to check disk space for {path}: {e}")
        # Return True to allow operation to proceed if we can't check
        # This is a safe default - we don't want to block recording due to check failure
        return True, 0


class AudioStorage:
    """Audio storage manager for whisper-dictate.

    Manages audio file storage with XDG Base Directory spec compliance,
    date-based directory structure, and unique filename generation.

    RESPONSIBILITY: Handle all audio file storage operations.
    BOUNDARIES:
    - DOES: Create directories, save/move/retrieve/delete audio files
    - DOES NOT: Handle transcription, database operations, or audio recording
    """

    def __init__(self, config: DatabaseConfig, paths: AudioPathResolver) -> None:
        """Initialize audio storage with configuration and an injected path resolver.

        Args:
            config: Database configuration containing recordings path (REQUIRED:
                a None config used to silently fall back to default paths,
                which broke user-configured recordings directories)
            paths: Injected pure path resolver (``whisper_dictate.util.paths.
                AudioPathResolver``) built from the same configuration; it is
                the single source of truth for all path computation
        """
        self._paths = paths
        self._recordings_path = paths.recordings_path
        logger.debug(f"AudioStorage initialized with path: {self._recordings_path}")

    @property
    def recordings_path(self) -> Path:
        """Get the base recordings directory path.

        Returns:
            Path: Full path to recordings directory
        """
        return self._recordings_path

    def check_disk_space(self, min_free_mb: int = DEFAULT_MIN_FREE_SPACE_MB) -> tuple[bool, int]:
        """Check available disk space for the recordings directory.

        Args:
            min_free_mb: Minimum free space required in MB (default: 100MB)

        Returns:
            Tuple[bool, int]: (has_space, available_mb) - True if enough space available,
                             and the available space in MB
        """
        return check_disk_space(self._recordings_path, min_free_mb)

    def get_disk_usage(self) -> dict[str, Any]:
        """Get disk usage statistics for the recordings directory's filesystem.

        Returns:
            dict: Disk usage statistics including total, used, and free space in bytes and MB
        """
        try:
            stat_result = os.statvfs(self._recordings_path)

            total_bytes = stat_result.f_blocks * stat_result.f_frsize
            used_bytes = (stat_result.f_blocks - stat_result.f_bfree) * stat_result.f_frsize
            available_bytes = stat_result.f_bavail * stat_result.f_frsize

            return {
                "total_bytes": total_bytes,
                "total_mb": round(total_bytes / (1024 * 1024), 2),
                "used_bytes": used_bytes,
                "used_mb": round(used_bytes / (1024 * 1024), 2),
                "available_bytes": available_bytes,
                "available_mb": round(available_bytes / (1024 * 1024), 2),
                "recordings_path": str(self._recordings_path),
            }
        except OSError as e:
            logger.warning(f"Failed to get disk usage for {self._recordings_path}: {e}")
            return {
                "error": str(e),
                "recordings_path": str(self._recordings_path),
            }

    def ensure_directory_exists(self, directory: Path) -> None:
        """Ensure a directory exists, creating it if necessary.

        Args:
            directory: Directory path to create
        """
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured directory exists: {directory}")

    def get_date_directory(self, timestamp: datetime | None = None, create: bool = True) -> Path:
        """Get the date-based directory for a recording.

        Args:
            timestamp: Datetime for the directory (defaults to now)
            create: Whether to create the directory if it doesn't exist

        Returns:
            Path: Full path to the date-based directory
        """
        directory = self._paths.get_date_directory(timestamp)

        if create:
            self.ensure_directory_exists(directory)

        return directory

    def generate_storage_path(self, timestamp: datetime | None = None, suffix: str = "wav") -> tuple[Path, str]:
        """Generate a unique storage path for a new recording.

        Args:
            timestamp: Datetime for the filename (defaults to now)
            suffix: File extension (without dot)

        Returns:
            tuple[Path, str]: Full file path and the filename
        """
        # Generate unique storage path (pure computation)
        dest_path, filename = self._paths.generate_storage_path(timestamp, suffix)

        # Ensure destination directory exists
        self.ensure_directory_exists(dest_path.parent)

        # Return full path
        return dest_path, filename

    def stage_audio(
        self,
        source_path: Path,
        timestamp: datetime | None = None,
        suffix: str = "wav",
    ) -> StagedAudio:
        """Stage an audio file for atomic persistence.

        Copies the source into a temporary staging file inside the destination
        directory. The caller should claim the final path in the database
        (claim-first) and then call ``finalize_audio()`` so the final path only
        ever appears with complete content.

        Args:
            source_path: Path to the source audio file (e.g., temp file)
            timestamp: Datetime for the filename (defaults to now)
            suffix: File extension (without dot)

        Returns:
            StagedAudio: Staging details (staged path, final path, relative path)

        Raises:
            FileNotFoundError: If source file doesn't exist
            OSError: If staging the file fails
        """
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        # Generate unique storage path
        dest_path, filename = self.generate_storage_path(timestamp, suffix)

        # Ensure destination directory exists
        self.ensure_directory_exists(dest_path.parent)

        staged_path = dest_path.parent / f"{STAGING_PREFIX}{filename}.{self._paths.generate_random_suffix(6)}.part"

        try:
            shutil.copy2(str(source_path), str(staged_path))
        except Exception as e:
            with contextlib.suppress(OSError):
                staged_path.unlink(missing_ok=True)
            logger.error(f"Failed to stage audio file: {e}")
            raise OSError(f"Failed to stage audio file: {e}") from e

        relative_path = dest_path.relative_to(self._recordings_path)
        return StagedAudio(
            staged_path=staged_path,
            final_path=dest_path,
            relative_path=str(relative_path),
        )

    def finalize_audio(self, staged: StagedAudio) -> Path:
        """Atomically move a staged audio file into its final location.

        Uses ``os.replace()`` within the destination directory so the final
        path never contains a partial file and concurrent readers observe
        either the old state or the complete new file.

        Args:
            staged: Staging details returned by ``stage_audio()``

        Returns:
            Path: Final path of the saved file

        Raises:
            OSError: If the replace step fails (staging file is cleaned up)
        """
        try:
            os.replace(staged.staged_path, staged.final_path)
        except Exception as e:
            with contextlib.suppress(OSError):
                staged.staged_path.unlink(missing_ok=True)
            logger.error(f"Failed to finalize audio file: {e}")
            raise OSError(f"Failed to finalize audio file: {e}") from e

        logger.info(f"Audio saved to: {staged.final_path}")
        return staged.final_path

    def save_audio(
        self,
        source_path: Path,
        timestamp: datetime | None = None,
        suffix: str = "wav",
    ) -> tuple[Path, str]:
        """Save an audio file from temporary storage to persistent storage.

        Stages the file inside the destination directory and atomically
        finalizes it with ``os.replace()``, so the final path never contains a
        partial file. Note: this convenience wrapper does not claim the path in
        the database; callers that track recordings in the database should use
        ``stage_audio()``/``finalize_audio()`` and update the row's ``file_path``
        between the two steps (claim-first ordering).

        Args:
            source_path: Path to the source audio file (e.g., temp file)
            timestamp: Datetime for the filename (defaults to now)
            suffix: File extension (without dot)

        Returns:
            tuple[Path, str]: Full path to saved file and relative path from recordings root

        Raises:
            FileNotFoundError: If source file doesn't exist
            OSError: If staging or finalizing fails
        """
        staged = self.stage_audio(source_path, timestamp, suffix)
        final_path = self.finalize_audio(staged)
        # Preserve save_audio's historical move semantics: stage_audio copies,
        # so the source would survive. Callers of this convenience wrapper
        # expect the source to be consumed, so remove it only after the
        # atomic replace succeeded.
        source_path.unlink()
        return final_path, staged.relative_path

    def copy_audio(
        self,
        source_path: Path,
        timestamp: datetime | None = None,
        suffix: str = "wav",
    ) -> tuple[Path, str]:
        """Copy an audio file to persistent storage (keeps original).

        Args:
            source_path: Path to the source audio file
            timestamp: Datetime for the filename (defaults to now)
            suffix: File extension (without dot)

        Returns:
            tuple[Path, str]: Full path to copied file and relative path from recordings root

        Raises:
            FileNotFoundError: If source file doesn't exist
            IOError: If file copy fails
        """
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        # Generate unique storage path
        dest_path, filename = self.generate_storage_path(timestamp, suffix)

        # Ensure destination directory exists
        self.ensure_directory_exists(dest_path.parent)

        # Copy file to persistent storage
        try:
            shutil.copy2(str(source_path), str(dest_path))
            logger.info(f"Audio copied to: {dest_path}")
        except Exception as e:
            logger.error(f"Failed to copy audio file: {e}")
            raise OSError(f"Failed to copy audio file: {e}") from e

        # Return full path and relative path from recordings root
        relative_path = dest_path.relative_to(self._recordings_path)
        return dest_path, str(relative_path)

    def _resolve_contained(self, relative_path: str) -> Path:
        """Resolve a stored path against the recordings root, enforcing containment.

        Delegates the pure containment validation to the injected
        ``AudioPathResolver``.

        Args:
            relative_path: Stored path (relative to the recordings root, or a
                legacy absolute path that resolves inside the root)

        Returns:
            Path: Fully resolved path inside the recordings root

        Raises:
            NoAudioFileError: If the stored path is empty (no file stored)
            UnsafeAudioPathError: If the path escapes the recordings root
        """
        return self._paths.resolve_contained(relative_path)

    def get_audio_path(self, relative_path: str, verify_exists: bool = False) -> Path:
        """Resolve a stored path to an absolute path inside the recordings directory.

        The stored path is resolved and containment-checked: absolute paths and
        ``..`` traversal are rejected unless they resolve inside the recordings
        root, and an empty path is the "no file" sentinel.

        Args:
            relative_path: Relative path from recordings root
            verify_exists: If True, raise FileNotFoundError if file doesn't exist

        Returns:
            Path: Absolute path to the audio file

        Raises:
            NoAudioFileError: If the stored path is empty (no file stored)
            UnsafeAudioPathError: If the path escapes the recordings root
            FileNotFoundError: If verify_exists is True and file doesn't exist
        """
        path = self._resolve_contained(relative_path)
        if verify_exists and not path.exists():
            raise FileNotFoundError(
                f"Audio file not found: {path}\nThe file may have been deleted or moved outside the application."
            )
        return path

    def verify_audio_file(self, relative_path: str) -> Path:
        """Verify that an audio file exists and return its absolute path.

        Args:
            relative_path: Relative path from recordings root

        Returns:
            Path: Absolute path to the audio file

        Raises:
            FileNotFoundError: If the file doesn't exist
        """
        return self.get_audio_path(relative_path, verify_exists=True)

    def get_audio(self, relative_path: str) -> bytes | None:
        """Read audio file contents.

        Args:
            relative_path: Relative path from recordings root

        Returns:
            Optional[bytes]: Audio file contents, or None if not found
        """
        try:
            full_path = self.get_audio_path(relative_path)
        except AudioPathError as e:
            logger.warning(f"Cannot read audio file: {e}")
            return None

        if not full_path.exists():
            logger.warning(f"Audio file not found: {full_path}")
            return None

        try:
            return full_path.read_bytes()
        except Exception as e:
            logger.error(f"Failed to read audio file: {e}")
            return None

    def delete_audio(self, relative_path: str) -> bool:
        """Delete an audio file.

        Files outside the recordings root are never deleted; rows without a
        stored file are a no-op.

        Args:
            relative_path: Relative path from recordings root

        Returns:
            bool: True if deleted, False if not found
        """
        try:
            full_path = self.get_audio_path(relative_path)
        except NoAudioFileError:
            return False
        except UnsafeAudioPathError as e:
            logger.warning(f"Refusing to delete audio file outside recordings root: {e}")
            return False

        if not full_path.exists():
            logger.warning(f"Audio file not found for deletion: {full_path}")
            return False

        try:
            full_path.unlink()
            logger.info(f"Audio file deleted: {full_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete audio file: {e}")
            return False

    def cleanup_empty_directories(self, base_path: Path | None = None) -> int:
        """Remove empty date-based directories.

        Args:
            base_path: Base directory to clean (defaults to recordings path)

        Returns:
            int: Number of directories removed
        """
        if base_path is None:
            base_path = self._recordings_path

        removed_count = 0

        # Walk through year/month/day directories and remove empty ones
        for year_dir in base_path.iterdir():
            if not year_dir.is_dir():
                continue

            for month_dir in year_dir.iterdir():
                if not month_dir.is_dir():
                    continue

                for day_dir in month_dir.iterdir():
                    if not day_dir.is_dir():
                        continue

                    # Check if directory is empty
                    if not any(day_dir.iterdir()):
                        try:
                            day_dir.rmdir()
                            removed_count += 1
                            logger.debug(f"Removed empty directory: {day_dir}")
                        except OSError:
                            pass

                # Check if month directory is empty
                if month_dir.is_dir() and not any(month_dir.iterdir()):
                    try:
                        month_dir.rmdir()
                        removed_count += 1
                        logger.debug(f"Removed empty directory: {month_dir}")
                    except OSError:
                        pass

            # Check if year directory is empty
            if year_dir.is_dir() and not any(year_dir.iterdir()):
                try:
                    year_dir.rmdir()
                    removed_count += 1
                    logger.debug(f"Removed empty directory: {year_dir}")
                except OSError:
                    pass

        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} empty directories")

        return removed_count

    def get_storage_stats(self) -> dict[str, Any]:
        """Get storage statistics.

        Returns:
            dict: Statistics including total files, total size, etc.
        """
        total_files = 0
        total_size = 0

        if self._recordings_path.exists():
            for path in self._recordings_path.rglob("*"):
                if path.is_file():
                    total_files += 1
                    total_size += path.stat().st_size

        return {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "recordings_path": str(self._recordings_path),
        }
