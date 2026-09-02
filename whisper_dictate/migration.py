"""State migration module for whisper-dictate.

Handles migration from legacy state files to the database:
- ~/.whisper-dictate-state (marker file)
- ~/.whisper-dictate-pid (contains arecord PID)
- Any JSON config files

Provides:
- Automatic migration detection on startup
- Manual migration trigger via CLI
- Backup and rollback support
- Migration status tracking
"""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from whisper_dictate.config import AppPaths, DatabaseConfig
from whisper_dictate.database import Database

logger = logging.getLogger(__name__)

# Legacy file paths — resolved through AppPaths (single source of truth) so
# migration reads exactly the same dotfiles whisper_dictate.toggle writes at
# runtime.
_paths = AppPaths()
LEGACY_STATE_FILE = _paths.legacy_state_file
LEGACY_PID_FILE = _paths.legacy_pid_file
LEGACY_AUDIO_FILE = _paths.legacy_audio_file

# Backup directory — inside the XDG data home, via AppPaths
BACKUP_DIR = _paths.backup_dir

# Migration status keys
MIGRATION_STATUS_KEY = "migration_status"
MIGRATION_COMPLETED = "completed"
MIGRATION_FAILED = "failed"
MIGRATION_PENDING = "pending"


class MigrationError(Exception):
    """Raised when migration fails."""

    pass


class MigrationManager:
    """Manages state migration from legacy files to database.

    RESPONSIBILITY: Handle migration of legacy state files to database storage.
    BOUNDARIES:
    - DOES: Detect, backup, migrate, and track migration status
    - DOES NOT: Handle database schema creation or other migrations
    """

    def __init__(
        self,
        db: Database | None = None,
        db_config: DatabaseConfig | None = None,
    ):
        """Initialize migration manager.

        Args:
            db: Database instance to operate on. Constructed by the caller
                (the CLI migrate command) from the loaded config so the
                user's configured database path is honored. When None, a
                Database is constructed here from db_config (or defaults).
            db_config: Database configuration used only when db is None
                (standalone callers). Defaults to DatabaseConfig().
        """
        if db is None:
            db = Database(db_config or DatabaseConfig())
        self._db = db
        self._backup_dir = BACKUP_DIR
        self._migration_log: list[dict[str, Any]] = []

    def initialize(self) -> None:
        """Initialize the database for migration.

        Raises:
            MigrationError: If database initialization fails
        """
        try:
            self._db.initialize()
            logger.info("Migration manager initialized")
        except Exception as e:
            raise MigrationError(f"Failed to initialize database: {e}") from e

    def detect_legacy_files(self) -> dict[str, bool]:
        """Detect which legacy files exist.

        Returns:
            dict: Dictionary mapping file names to existence status
        """
        return {
            "state_file": LEGACY_STATE_FILE.exists(),
            "pid_file": LEGACY_PID_FILE.exists(),
            "audio_file": LEGACY_AUDIO_FILE.exists(),
        }

    def is_migration_completed(self, force: bool = False) -> bool:
        """Check if migration has already been completed.

        Args:
            force: If True, always return False to force re-migration

        Returns:
            bool: True if migration was completed, False otherwise
        """
        if force:
            return False

        try:
            status = self._db.get_state(MIGRATION_STATUS_KEY)
            if status and isinstance(status, dict):
                return status.get("status") == MIGRATION_COMPLETED
        except Exception as e:
            logger.debug(f"Could not check migration status: {e}")

        return False

    def run_migration(self, force: bool = False) -> dict[str, Any]:
        """Run the complete migration process.

        Args:
            force: If True, force re-migration even if already completed

        Returns:
            dict: Migration result with success status and details

        Raises:
            MigrationError: If migration fails and rollback is not possible
        """
        self._migration_log = []
        self._log("INFO", "Starting migration process")

        # Check if already completed
        if self.is_migration_completed(force=force):
            if not force:
                self._log("INFO", "Migration already completed, skipping")
                return {
                    "success": True,
                    "skipped": True,
                    "message": "Migration already completed",
                }

            self._log("INFO", "Force re-migration requested")

        # Detect legacy files
        legacy_files = self.detect_legacy_files()
        has_legacy = any(legacy_files.values())

        if not has_legacy:
            self._log("INFO", "No legacy files found, nothing to migrate")
            self._set_migration_status(MIGRATION_COMPLETED)
            return {
                "success": True,
                "skipped": True,
                "message": "No legacy files to migrate",
            }

        self._log("INFO", f"Found legacy files: {legacy_files}")

        # Create backup - MUST succeed or abort migration
        backup_path = self._create_backup(legacy_files)
        if not backup_path:
            self._log("ERROR", "Failed to create backup, aborting migration")
            self._set_migration_status(MIGRATION_FAILED, error="Backup creation failed")
            raise MigrationError(
                "Backup creation failed, aborting migration to prevent data loss"
            )
        self._log("INFO", f"Created backup at: {backup_path}")

        # Perform migration in a transaction for atomicity
        try:
            with self._db.transaction():
                # Migrate state
                self._migrate_state(legacy_files)

                # Migrate PID if recording is in progress
                self._migrate_pid(legacy_files)

                # Mark as completed
                self._set_migration_status(MIGRATION_COMPLETED)

            self._log("INFO", "Migration completed successfully")

            # Verify migration after transaction commits
            self._verify_migration(legacy_files)

            # Remove legacy files after successful migration and verification
            self._remove_legacy_files(legacy_files)

            return {
                "success": True,
                "skipped": False,
                "migrated_files": legacy_files,
                "backup_path": str(backup_path),
            }

        except Exception as e:
            self._log("ERROR", f"Migration failed: {e}")

            # Attempt rollback
            self._rollback(backup_path, legacy_files)

            self._set_migration_status(MIGRATION_FAILED, error=str(e))
            raise MigrationError(f"Migration failed: {e}") from e

    def _create_backup(self, legacy_files: dict[str, bool]) -> Path | None:
        """Create backup of legacy files.

        Args:
            legacy_files: Dictionary of files to backup

        Returns:
            Optional[Path]: Path to backup directory, or None if failed
        """
        try:
            # Create backup directory with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self._backup_dir / f"migration_{timestamp}"
            backup_path.mkdir(parents=True, exist_ok=True)

            # Backup each legacy file that exists
            files_backed_up = []

            if legacy_files.get("state_file") and LEGACY_STATE_FILE.exists():
                dest = backup_path / LEGACY_STATE_FILE.name
                shutil.copy2(LEGACY_STATE_FILE, dest)
                files_backed_up.append(LEGACY_STATE_FILE.name)

            if legacy_files.get("pid_file") and LEGACY_PID_FILE.exists():
                dest = backup_path / LEGACY_PID_FILE.name
                shutil.copy2(LEGACY_PID_FILE, dest)
                files_backed_up.append(LEGACY_PID_FILE.name)

            if legacy_files.get("audio_file") and LEGACY_AUDIO_FILE.exists():
                dest = backup_path / LEGACY_AUDIO_FILE.name
                shutil.copy2(LEGACY_AUDIO_FILE, dest)
                files_backed_up.append(LEGACY_AUDIO_FILE.name)

            self._log("INFO", f"Backed up files: {files_backed_up}")
            return backup_path

        except Exception as e:
            self._log("ERROR", f"Backup failed: {e}")
            return None

    def _migrate_state(self, legacy_files: dict[str, bool]) -> None:
        """Migrate state file data to database.

        Args:
            legacy_files: Dictionary of legacy files to check
        """
        if not legacy_files.get("state_file"):
            return

        try:
            # Read state file (it's a marker file, but check for any content)
            state_data: dict[str, Any] = {
                "is_recording": LEGACY_STATE_FILE.exists(),
                "migrated_at": datetime.now().isoformat(),
                "source": "legacy_state_file",
            }

            # Try to read any state content if the file has data
            if LEGACY_STATE_FILE.exists() and LEGACY_STATE_FILE.stat().st_size > 0:
                try:
                    content = LEGACY_STATE_FILE.read_text().strip()
                    if content:
                        state_data["content"] = content
                except Exception:
                    pass

            # Store in database state table
            self._db.set_state("legacy_recording_state", state_data)
            self._log("INFO", "Migrated recording state to database")

        except Exception as e:
            self._log("ERROR", f"Failed to migrate state: {e}")
            raise

    def _migrate_pid(self, legacy_files: dict[str, bool]) -> None:
        """Migrate PID file data to database.

        Args:
            legacy_files: Dictionary of legacy files to check
        """
        if not legacy_files.get("pid_file"):
            return

        try:
            # Read PID file
            pid_value: int | None = None
            if LEGACY_PID_FILE.exists():
                try:
                    content = LEGACY_PID_FILE.read_text().strip()
                    pid_value = int(content) if content else None
                except (ValueError, OSError):
                    pass

            pid_data: dict[str, Any] = {
                "has_pid": pid_value is not None,
                "migrated_at": datetime.now().isoformat(),
                "source": "legacy_pid_file",
            }

            if pid_value is not None:
                pid_data["pid"] = pid_value

                # Check if process is still running
                try:
                    os.kill(
                        pid_value, 0
                    )  # Signal 0 doesn't kill, just checks existence
                    pid_data["process_exists"] = True
                except OSError:
                    pid_data["process_exists"] = False

            # Store in database state table
            self._db.set_state("legacy_pid_state", pid_data)
            self._log("INFO", f"Migrated PID data to database (PID: {pid_value})")

        except Exception as e:
            self._log("ERROR", f"Failed to migrate PID: {e}")
            raise

    def _rollback(
        self, backup_path: Path | None, legacy_files: dict[str, bool]
    ) -> None:
        """Attempt to rollback migration.

        Args:
            backup_path: Path to the backup directory
            legacy_files: Original legacy files that were migrated
        """
        self._log("WARNING", "Attempting rollback")

        # Delete migrated state from database
        try:
            self._db.delete_state("legacy_recording_state")
            self._db.delete_state("legacy_pid_state")
            self._log("INFO", "Rolled back database state")
        except Exception as e:
            self._log("ERROR", f"Failed to rollback database state: {e}")

        # Note: We don't delete the backup - it's kept for manual recovery
        if backup_path:
            self._log("INFO", f"Backup preserved at: {backup_path}")

    def _set_migration_status(self, status: str, error: str | None = None) -> None:
        """Set migration status in database.

        Args:
            status: Migration status (completed, failed, pending)
            error: Optional error message
        """
        status_data: dict[str, Any] = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "log": self._migration_log,
        }

        if error:
            status_data["error"] = error

        self._db.set_state(MIGRATION_STATUS_KEY, status_data)

    def _verify_migration(self, legacy_files: dict[str, bool]) -> None:
        """Verify migration succeeded by reading back stored data.

        Args:
            legacy_files: Dictionary of legacy files that were migrated

        Raises:
            MigrationError: If verification fails
        """
        self._log("INFO", "Verifying migration...")

        try:
            # Verify recording state
            if legacy_files.get("state_file"):
                state = self._db.get_state("legacy_recording_state")
                if not state or not isinstance(state, dict):
                    raise MigrationError(
                        "Verification failed: legacy_recording_state not found"
                    )
                if "migrated_at" not in state:
                    raise MigrationError(
                        "Verification failed: migrated_at not in state"
                    )
                self._log("INFO", "Recording state verification passed")

            # Verify PID state
            if legacy_files.get("pid_file"):
                pid_state = self._db.get_state("legacy_pid_state")
                if not pid_state or not isinstance(pid_state, dict):
                    raise MigrationError(
                        "Verification failed: legacy_pid_state not found"
                    )
                if "migrated_at" not in pid_state:
                    raise MigrationError(
                        "Verification failed: migrated_at not in pid_state"
                    )
                self._log("INFO", "PID state verification passed")

            # Verify migration status
            status = self._db.get_state(MIGRATION_STATUS_KEY)
            if not status or status.get("status") != MIGRATION_COMPLETED:
                raise MigrationError(
                    "Verification failed: migration status not completed"
                )

            self._log("INFO", "All migration verification checks passed")

        except MigrationError:
            raise
        except Exception as e:
            raise MigrationError(f"Verification failed: {e}") from e

    def _remove_legacy_files(self, legacy_files: dict[str, bool]) -> None:
        """Remove legacy files after successful migration.

        Args:
            legacy_files: Dictionary of legacy files to remove
        """
        if legacy_files.get("state_file") and LEGACY_STATE_FILE.exists():
            try:
                LEGACY_STATE_FILE.unlink(missing_ok=True)
                self._log("INFO", f"Removed legacy state file: {LEGACY_STATE_FILE}")
            except OSError as e:
                self._log("WARNING", f"Failed to remove legacy state file: {e}")

        if legacy_files.get("pid_file") and LEGACY_PID_FILE.exists():
            try:
                LEGACY_PID_FILE.unlink(missing_ok=True)
                self._log("INFO", f"Removed legacy PID file: {LEGACY_PID_FILE}")
            except OSError as e:
                self._log("WARNING", f"Failed to remove legacy PID file: {e}")

        # Note: We keep the audio file as it contains actual recording data
        # that the user may want to keep

    def _log(self, level: str, message: str) -> None:
        """Add an entry to the migration log.

        Args:
            level: Log level
            message: Log message
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
        }
        self._migration_log.append(entry)
        logger.log(getattr(logging, level), f"[Migration] {message}")

    def get_migration_log(self) -> list[dict[str, Any]]:
        """Get the migration log.

        Returns:
            list: List of log entries
        """
        return self._migration_log.copy()

    def close(self) -> None:
        """Close the database connection.

        This should be called after migration is complete to properly
        release database resources.
        """
        self._db.close()


def run_migration(
    force: bool = False,
    db: Database | None = None,
    db_config: DatabaseConfig | None = None,
) -> dict[str, Any]:
    """Run state migration.

    This is a convenience function for CLI usage.

    Args:
        force: If True, force re-migration even if already completed
        db: Database instance to operate on (constructed from db_config when None)
        db_config: Database configuration used only when db is None

    Returns:
        dict: Migration result

    Raises:
        MigrationError: If migration fails
    """
    manager = MigrationManager(db=db, db_config=db_config)
    try:
        manager.initialize()
        return manager.run_migration(force=force)
    finally:
        manager.close()


def check_migration_status(
    db: Database | None = None,
    db_config: DatabaseConfig | None = None,
) -> dict[str, Any]:
    """Check migration status.

    Args:
        db: Database instance to operate on (constructed from db_config when None)
        db_config: Database configuration used only when db is None

    Returns:
        dict: Status information including whether migration is needed
    """
    manager = MigrationManager(db=db, db_config=db_config)
    try:
        manager.initialize()

        legacy_files = manager.detect_legacy_files()
        is_completed = manager.is_migration_completed()

        return {
            "legacy_files": legacy_files,
            "has_legacy_files": any(legacy_files.values()),
            "migration_completed": is_completed,
            "migration_needed": any(legacy_files.values()) and not is_completed,
        }
    finally:
        manager.close()
