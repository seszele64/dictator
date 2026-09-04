"""Orphan scan and cleanup for recorded audio files.

Finds audio files that exist in the recordings directory but are not
referenced in the database, and (optionally) deletes them. The scan is the
safety-critical half of `audio cleanup`: it must never classify a real
recording as an orphan (mass-deletion hazard), so it compares
resolved-vs-resolved paths and skips in-progress staging saves.

State is explicit, not module-level: an ``OrphanScanner`` is constructed with
the ``AudioStorage`` that owns the recordings root, and the ``Database`` is
passed to ``find_orphans()`` per call. The old flat-function/global-getter
pattern is dead (S3 anti-goal).
"""

import logging
import time
from typing import Any

from whisper_dictate.database import Database
from whisper_dictate.storage.audio_storage import STAGING_PREFIX, AudioStorage
from whisper_dictate.util.paths import AudioPathError

logger = logging.getLogger(__name__)

# Age (seconds) after which a leftover staging file is treated as an orphan by
# the cleanup scan. Younger files may belong to a save currently in progress.
STAGING_RETENTION_SECONDS = 3600


class OrphanScanner:
    """Finds and cleans up orphaned audio files in the recordings directory.

    RESPONSIBILITY: Compare the recordings directory (owned by the injected
    ``AudioStorage``) against database records and report/delete the
    difference.
    BOUNDARIES:
    - DOES: Scan for orphaned files, delete them on request (real or dry-run)
    - DOES NOT: Create, move, or read audio content; touch non-orphan files
    """

    def __init__(self, storage: AudioStorage) -> None:
        """Initialize the scanner with the storage providing the recordings root.

        Args:
            storage: AudioStorage instance providing the recordings root and
                the containment-checked path resolution. Explicit (not a
                global): this fixes a default-configuration bug where the
                scan silently used DEFAULT recordings paths regardless of
                what the user configured.
        """
        self._storage = storage

    def find_orphans(self, db: Database) -> list[dict[str, Any]]:
        """Scan for orphaned audio files not referenced in the database.

        Compares files in the recordings directory against database records
        to find audio files that exist on disk but are not in the database.

        Args:
            db: Database instance (must have list_recordings method)

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
        recordings_path = self._storage.recordings_path.resolve()

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
                    resolved = self._storage.get_audio_path(file_path)
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

    def cleanup(self, orphans: list[dict[str, Any]], dry_run: bool = True) -> tuple[int, int]:
        """Clean up the given orphaned audio files.

        The caller supplies the scan result (``find_orphans()`` output) so a
        CLI invocation scans the database and filesystem exactly once and the
        deletion list is identical to the displayed one — no hidden re-scan.

        Args:
            orphans: Orphaned file info dicts as returned by ``find_orphans()``
            dry_run: If True, only return what would be deleted without deleting

        Returns:
            tuple[int, int]: (deleted_count, total_size_freed)
                - deleted_count: Number of files deleted (or would be deleted)
                - total_size_freed: Total size in bytes freed (or would be freed)
        """
        deleted_count = 0
        total_size_freed = 0

        for file_info in orphans:
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
