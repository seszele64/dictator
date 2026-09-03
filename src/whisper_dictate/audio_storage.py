"""Audio storage management for whisper-dictate.

Provides audio file storage with:
- XDG Base Directory spec compliance
- Date-based directory structure (YYYY/MM/DD)
- Unique filename generation (timestamp + random suffix)
- File save, retrieve, and cleanup operations
- Disk space checking for safe recording
"""

import contextlib
import logging
import os
import random
import shutil
import string
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from whisper_dictate.config import DatabaseConfig
from whisper_dictate.database import Database

logger = logging.getLogger(__name__)

# Length of random suffix for unique filenames
RANDOM_SUFFIX_LENGTH = 8

# Default minimum free space threshold in MB
DEFAULT_MIN_FREE_SPACE_MB = 100

# Prefix for staged (in-progress) audio files inside the destination directory.
# Files are staged under this name and atomically renamed into place, so the
# final path never contains a partial file.
STAGING_PREFIX = ".staging-"

# Age (seconds) after which a leftover staging file is treated as an orphan by
# the cleanup scan. Younger files may belong to a save currently in progress.
STAGING_RETENTION_SECONDS = 3600


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


class AudioStorage:
    """Audio storage manager for whisper-dictate.

    Manages audio file storage with XDG Base Directory spec compliance,
    date-based directory structure, and unique filename generation.

    RESPONSIBILITY: Handle all audio file storage operations.
    BOUNDARIES:
    - DOES: Create directories, save/move/retrieve/delete audio files
    - DOES NOT: Handle transcription, database operations, or audio recording
    """

    def __init__(self, config: DatabaseConfig):
        """Initialize audio storage with configuration.

        Args:
            config: Database configuration containing recordings path (REQUIRED:
                a None config used to silently fall back to default paths,
                which broke user-configured recordings directories)
        """
        self._config = config
        self._recordings_path = config.get_recordings_path()
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
        directory = _get_date_based_path(self._recordings_path, timestamp)

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
        # Get date-based directory
        directory = self.get_date_directory(timestamp, create=True)

        # Generate unique filename
        filename = _generate_unique_filename(timestamp, suffix)

        # Return full path
        return directory / filename, filename

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

        staged_path = dest_path.parent / f"{STAGING_PREFIX}{filename}.{_generate_random_suffix(6)}.part"

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


# ============ Orphaned File Cleanup Functions ============


def get_orphaned_files(db: Database, storage: AudioStorage) -> list[dict[str, Any]]:
    """Scan for orphaned audio files not referenced in the database.

    Compares files in the recordings directory against database records
    to find audio files that exist on disk but are not in the database.

    Args:
        db: Database instance (must have list_recordings method)
        storage: AudioStorage instance providing the recordings root. Explicit
            (not a global): this fixes a default-configuration bug where the
            scan silently used DEFAULT recordings paths regardless of what
            the user configured.

    Returns:
        list[dict]: List of orphaned file info with keys:
            - path: Path to the orphaned file
            - relative_path: Relative path from recordings root
            - size: File size in bytes
            - modified: Last modified timestamp
    """
    # Compare resolved-vs-resolved: the DB side canonicalizes stored paths
    # through get_audio_path() (resolve()), so the scan root must be
    # canonicalized too. With the raw configured root (e.g. a symlinked
    # recordings directory), every resolved DB path fails relative_to() and
    # gets dropped from db_files — making all real recordings look orphaned
    # and exposing them to mass deletion via `audio cleanup --confirm`.
    recordings_path = storage.recordings_path.resolve()

    if not recordings_path.exists():
        logger.info("Recordings directory does not exist, no orphaned files")
        return []

    # Get all file paths from the filesystem
    filesystem_files: set[str] = set()
    orphaned_files = []

    if recordings_path.exists():
        now = time.time()
        for path in recordings_path.rglob("*"):
            if not path.is_file():
                continue
            # Skip staging files from saves that may still be in progress;
            # older leftovers are treated as orphans and cleaned up.
            if path.name.startswith(STAGING_PREFIX):
                try:
                    age = now - path.stat().st_mtime
                except OSError:
                    continue
                if age < STAGING_RETENTION_SECONDS:
                    logger.debug(f"Skipping in-progress staging file: {path}")
                    continue
            try:
                relative = str(path.relative_to(recordings_path))
                filesystem_files.add(relative)
            except ValueError:
                logger.warning(f"Could not compute relative path for: {path}")

    # Get all file paths from the database, normalized through the containment
    # check so empty/unsafe stored paths reference nothing inside the tree and
    # legacy absolute in-root paths match their relative form.
    db_files: set[str] = set()
    try:
        # Use a high limit to get all recordings
        recordings = db.list_recordings(limit=100000, offset=0)
        for recording in recordings:
            file_path = recording.get("file_path")
            if not file_path:
                # Empty file_path is the "no file" sentinel
                continue
            try:
                resolved = storage.get_audio_path(file_path)
            except AudioPathError as e:
                logger.warning(
                    f"Recording path {file_path!r} not accessible "
                    f"({type(e).__name__}); its file will not be treated for cleanup"
                )
                continue
            try:
                db_files.add(str(resolved.relative_to(recordings_path)))
            except ValueError:
                logger.warning(f"Could not normalize stored path: {file_path}")
    except Exception as e:
        logger.error(f"Failed to fetch recordings from database: {e}")
        return []

    # Find orphaned files (in filesystem but not in database)
    for relative_path in filesystem_files:
        if relative_path not in db_files:
            full_path = recordings_path / relative_path
            try:
                stat = full_path.stat()
                orphaned_files.append(
                    {
                        "path": full_path,
                        "relative_path": relative_path,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    }
                )
            except OSError as e:
                logger.warning(f"Could not stat file {full_path}: {e}")

    logger.info(f"Found {len(orphaned_files)} orphaned audio files")

    return orphaned_files


def cleanup_orphaned_files(db: Database, storage: AudioStorage, dry_run: bool = True) -> tuple[int, int]:
    """Clean up orphaned audio files not referenced in the database.

    Args:
        db: Database instance with sync methods
        storage: AudioStorage instance providing the recordings root (explicit,
            not a global - see get_orphaned_files)
        dry_run: If True, only return what would be deleted without deleting

    Returns:
        tuple[int, int]: (deleted_count, total_size_freed)
            - deleted_count: Number of files deleted (or would be deleted)
            - total_size_freed: Total size in bytes freed (or would be freed)
    """
    orphaned_files = get_orphaned_files(db, storage)

    deleted_count = 0
    total_size_freed = 0

    for file_info in orphaned_files:
        file_path = file_info["path"]
        file_size = file_info["size"]

        if dry_run:
            logger.info(f"[DRY RUN] Would delete orphaned file: {file_path}")
            deleted_count += 1
            total_size_freed += file_size
        else:
            try:
                file_path.unlink()
                logger.info(f"Deleted orphaned file: {file_path}")
                deleted_count += 1
                total_size_freed += file_size
            except OSError as e:
                logger.error(f"Failed to delete orphaned file {file_path}: {e}")

    if dry_run:
        logger.info(f"[DRY RUN] Would delete {deleted_count} orphaned files, freeing {total_size_freed} bytes")
    else:
        logger.info(f"Deleted {deleted_count} orphaned files, freed {total_size_freed} bytes")

    return deleted_count, total_size_freed
