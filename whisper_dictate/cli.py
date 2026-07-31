"""Command-line interface for whisper-dictate."""

import logging
import sys
from pathlib import Path

import click

from whisper_dictate.audio_storage import check_disk_space
from whisper_dictate.cli_helpers import with_database
from whisper_dictate.config import DatabaseConfig, load_config
from whisper_dictate.database import get_database
from whisper_dictate.dictation import DictationService


def setup_logging(level: str, enable_db_logging: bool = True):
    """Configure application logging with file and optional database output.

    Returns:
        The DatabaseLogHandler if database logging was enabled, otherwise None.
    """
    from pathlib import Path

    # Create log directory
    log_dir = Path.home() / ".local" / "share" / "whisper-dictate"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "whisper-dictate.log"

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(getattr(logging, level.upper()))
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Add database logging handler if enabled
    if enable_db_logging:
        try:
            from whisper_dictate.db_logging import DatabaseLogHandler

            # Get or create database
            db_config = DatabaseConfig()
            db = get_database(db_config)

            # Initialize database synchronously for logging
            db.initialize()

            # Add database handler
            db_handler = DatabaseLogHandler(database=db)
            db_handler.setLevel(getattr(logging, level.upper()))
            db_handler.setFormatter(formatter)
            root_logger.addHandler(db_handler)

            # Run log retention cleanup
            retention_days = db_config.log_retention_days
            deleted = db.cleanup_old_logs(retention_days)
            if deleted > 0:
                root_logger.info(f"Cleaned up {deleted} old log entries")

            return db_handler

        except Exception as e:
            # Database logging is optional - continue without it
            root_logger.debug(f"Database logging not available: {e}")

    return None


@click.group()
@click.option("--log-level", default="INFO", help="Logging level")
@click.pass_context
def cli(ctx: click.Context, log_level: str) -> None:
    """Whisper-dictate: Voice-to-text dictation with clipboard integration."""
    db_log_handler = setup_logging(log_level)
    if db_log_handler is not None:
        ctx.call_on_close(db_log_handler.close)
    ctx.ensure_object(dict)

    try:
        config = load_config()
        ctx.obj["config"] = config
        service = DictationService(config)
        ctx.obj["service"] = service

        # Register cleanup to close service after any command
        ctx.call_on_close(service.close)
    except ValueError as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--duration", type=float, help="Recording duration in seconds")
@click.pass_context
def dictate(ctx: click.Context, duration: float | None) -> None:
    """Record audio and transcribe it to text."""
    service = ctx.obj["service"]

    try:
        # Check disk space before recording
        db_config = DatabaseConfig()
        has_space, available_mb = check_disk_space(
            db_config.get_recordings_path(), db_config.min_free_space_mb
        )
        if not has_space:
            click.echo(
                f"⚠️  Warning: Low disk space (only {available_mb} MB available).\n"
                "   Recording may fail if disk fills up."
            )

        click.echo("🎤 Recording... (Press Ctrl+C to stop early)")

        result = service.dictate(duration)

        if result:
            click.echo(f"✅ Transcription: {result.text}")
            if result.language:
                click.echo(f"🌐 Language: {result.language}")
        else:
            click.echo("❌ Dictation failed", err=True)
            sys.exit(1)

    except KeyboardInterrupt:
        click.echo("\n⏹️  Recording stopped by user")
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def info(ctx: click.Context) -> None:
    """Display system information and configuration."""
    service = ctx.obj["service"]
    info = service.get_system_info()

    click.echo("🔍 System Information:")
    click.echo("=" * 40)

    click.echo("\n🎤 Audio Devices:")
    for device in info["audio_devices"]:
        click.echo(f"  • {device}")

    click.echo("\n📋 Clipboard Tools:")
    for tool in info["clipboard_tools"]:
        click.echo(f"  • {tool}")
    click.echo("\n⚙️  Configuration:")
    for key, value in info["config"].items():
        click.echo(f"  • {key}: {value}")

    click.echo("\n📊 Logging:")
    from pathlib import Path

    log_file = (
        Path.home() / ".local" / "share" / "whisper-dictate" / "whisper-dictate.log"
    )
    click.echo(f"  • Log file: {log_file}")
    click.echo(f"  • View logs: tail -f {log_file}")


@click.group()
def logs() -> None:
    """Query and manage application logs stored in the database.

    This command group provides functionality to view, filter,
    and export application logs.
    """
    pass


@logs.command("list")
@click.option(
    "--level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Filter by log level",
)
@click.option("--source", help="Filter by source module")
@click.option(
    "--from-time", help="Filter from timestamp (ISO format: YYYY-MM-DD HH:MM:SS)"
)
@click.option("--to-time", help="Filter to timestamp (ISO format: YYYY-MM-DD HH:MM:SS)")
@click.option(
    "--limit", type=int, default=100, help="Maximum number of logs to display"
)
@with_database
def list_logs(
    ctx: click.Context,
    level: str | None,
    source: str | None,
    from_time: str | None,
    to_time: str | None,
    limit: int,
) -> None:
    """List application logs with optional filters.

    Examples:
        whisper-dictate logs list
        whisper-dictate logs list --level ERROR
        whisper-dictate logs list --source whisper_dictate.audio --limit 50
        whisper-dictate logs list --from-time "2024-01-01" --to-time "2024-01-31"
    """
    import json

    db = ctx.obj["db"]

    try:
        logs = db.query_logs(
            level=level,
            source=source,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
        )

        if not logs:
            click.echo("No logs found matching the specified criteria.")
            return

        # Display logs
        click.echo(f"Found {len(logs)} log entries:\n")
        for log in logs:
            timestamp = log.get("timestamp", "N/A")
            lvl = log.get("level", "N/A")
            src = log.get("source", "N/A")
            msg = log.get("message", "")

            # Color code by level
            if lvl == "ERROR":
                lvl_display = click.style(lvl, fg="red")
            elif lvl == "WARNING":
                lvl_display = click.style(lvl, fg="yellow")
            elif lvl == "INFO":
                lvl_display = click.style(lvl, fg="green")
            else:
                lvl_display = lvl

            click.echo(f"{timestamp} | {lvl_display:8} | {src:30} | {msg}")

            # Display metadata if present
            if log.get("metadata_json"):
                try:
                    metadata = json.loads(log["metadata_json"])
                    click.echo(f"       Metadata: {metadata}")
                except json.JSONDecodeError:
                    pass

    except Exception as e:
        click.echo(f"Error querying logs: {e}", err=True)
        sys.exit(1)


@logs.command("export")
@click.argument("filename")
@click.option(
    "--level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Filter by log level",
)
@click.option("--source", help="Filter by source module")
@click.option("--from-time", help="Filter from timestamp (ISO format)")
@click.option("--to-time", help="Filter to timestamp (ISO format)")
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Export format",
)
@with_database
def export_logs(
    ctx: click.Context,
    filename: str,
    level: str | None,
    source: str | None,
    from_time: str | None,
    to_time: str | None,
    format: str,
) -> None:
    """Export logs to a file.

    Examples:
        whisper-dictate logs export logs.txt
        whisper-dictate logs export error_logs.json --level ERROR --format json
    """
    import json

    db = ctx.obj["db"]

    try:
        # Path validation - check if export is outside current directory
        export_path = Path(filename).resolve()
        cwd = Path.cwd().resolve()

        try:
            export_path.relative_to(cwd)
        except ValueError:
            # Path is outside current directory tree
            if not click.confirm(
                f"Warning: Writing to path outside current directory:\n"
                f"  {export_path}\n"
                f"Continue?"
            ):
                click.echo("Export cancelled.")
                return

        # Get all logs (no limit for export)
        logs = db.query_logs(
            level=level,
            source=source,
            from_time=from_time,
            to_time=to_time,
            limit=10000,  # High limit for export
        )

        if not logs:
            click.echo("No logs found matching the specified criteria.")
            return

        # Write to file
        if format == "json":
            with open(export_path, "w") as f:
                json.dump(logs, f, indent=2)
        else:
            with open(export_path, "w") as f:
                for log in logs:
                    timestamp = log.get("timestamp", "N/A")
                    lvl = log.get("level", "N/A")
                    src = log.get("source", "N/A")
                    msg = log.get("message", "")
                    f.write(f"{timestamp} | {lvl:8} | {src:30} | {msg}\n")

        click.echo("Warning: Exported logs may contain sensitive information. Handle with care.")
        click.echo(f"Exported {len(logs)} log entries to {export_path}")

    except Exception as e:
        click.echo(f"Error exporting logs: {e}", err=True)
        sys.exit(1)


@logs.command("cleanup")
@click.option(
    "--days",
    type=int,
    default=None,
    help="Delete logs older than N days (default: use configured retention)",
)
@with_database
def cleanup_logs(ctx: click.Context, days: int | None) -> None:
    """Clean up old logs based on retention policy.

    Examples:
        whisper-dictate logs cleanup
        whisper-dictate logs cleanup --days 7
    """
    db = ctx.obj["db"]
    db_config = DatabaseConfig()

    try:
        # Get retention days from config if not provided
        retention_days = db_config.log_retention_days if days is None else days

        deleted = db.cleanup_old_logs(retention_days)

        click.echo(f"Cleaned up {deleted} log entries older than {retention_days} days")

    except Exception as e:
        click.echo(f"Error cleaning up logs: {e}", err=True)
        sys.exit(1)


# ============ History Command Group ============


@click.group()
def history() -> None:
    """Query and manage transcription history stored in the database.

    This command group provides functionality to view, search,
    and delete past transcriptions.
    """
    pass


@history.command("list")
@click.option(
    "--limit", type=int, default=20, help="Maximum number of transcriptions to display"
)
@click.option("--date", help="Filter by date (YYYY-MM-DD format)")
@with_database
def list_history(ctx: click.Context, limit: int, date: str | None) -> None:
    """List recent transcriptions with pagination.

    Examples:
        whisper-dictate history list
        whisper-dictate history list --limit 10
        whisper-dictate history list --date 2024-03-15
    """
    db = ctx.obj["db"]

    try:
        transcriptions = db.list_transcriptions(limit=limit, date=date)

        if not transcriptions:
            click.echo("No transcriptions found.")
            return

        click.echo(
            f"Recent Transcriptions (showing {len(transcriptions)} of {len(transcriptions)}):\n"
        )
        click.echo(f"{'ID':<5} {'Date':<20} {'Duration':<10} {'Preview':<50}")
        click.echo("-" * 90)

        for t in transcriptions:
            # Format timestamp
            timestamp = t.get("timestamp", "N/A")
            date_str = timestamp.split()[0] if timestamp != "N/A" else "N/A"
            time_str = (
                timestamp.split()[1][:8]
                if " " in timestamp and len(timestamp.split()) > 1
                else ""
            )

            # Format duration
            duration = t.get("duration")
            duration_str = f"{duration:.1f}s" if duration else "N/A"

            # Truncate text for preview
            text = t.get("text", "")
            preview = text[:47] + "..." if len(text) > 50 else text

            click.echo(
                f"{t['id']:<5} {date_str} {time_str:<10} {duration_str:<10} {preview:<50}"
            )

    except Exception as e:
        click.echo(f"Error listing transcriptions: {e}", err=True)
        sys.exit(1)


@history.command("show")
@click.argument("transcript_id", type=int)
@click.option("--audio", is_flag=True, help="Show audio file path")
@with_database
def show_history(ctx: click.Context, transcript_id: int, audio: bool) -> None:
    """Show full details of a transcription by ID.

    Examples:
        whisper-dictate history show 42
        whisper-dictate history show 42 --audio
    """
    from whisper_dictate.audio_storage import get_audio_storage

    db = ctx.obj["db"]
    db_config = DatabaseConfig()

    try:
        transcription = db.get_transcription_with_recording(transcript_id)

        if not transcription:
            click.echo(
                f"Error: Transcription with ID {transcript_id} not found.", err=True
            )
            sys.exit(1)

        click.echo("=" * 60)
        click.echo(f"Transcription #{transcription['id']}")
        click.echo("=" * 60)

        # Timestamp
        timestamp = transcription.get("timestamp", "N/A")
        click.echo(f"\n📅 Date: {timestamp}")

        # Duration
        duration = transcription.get("duration")
        if duration:
            click.echo(f"⏱️  Duration: {duration:.1f} seconds")

        # Language
        language = transcription.get("language")
        if language:
            click.echo(f"🌐 Language: {language}")

        # Model
        model = transcription.get("model_used", "N/A")
        click.echo(f"🤖 Model: {model}")

        # Confidence
        confidence = transcription.get("confidence")
        if confidence:
            click.echo(f"📊 Confidence: {confidence:.1%}")

        # Audio file path
        if audio:
            try:
                audio_storage = get_audio_storage(db_config)
                audio_path = audio_storage.get_audio_path(
                    transcription["file_path"], verify_exists=True
                )
                click.echo(f"\n🎵 Audio File: {audio_path}")
            except FileNotFoundError as e:
                click.echo("\n⚠️  Audio file not found!", err=True)
                click.echo(f"   {e}", err=True)
                sys.exit(1)

        # Full transcript text
        click.echo("\n" + "-" * 60)
        click.echo("📝 Transcript:")
        click.echo("-" * 60)
        click.echo(transcription.get("text", ""))

    except Exception as e:
        click.echo(f"Error showing transcription: {e}", err=True)
        sys.exit(1)


@history.command("search")
@click.argument("query")
@click.option(
    "--limit", type=int, default=20, help="Maximum number of results to display"
)
@with_database
def search_history(ctx: click.Context, query: str, limit: int) -> None:
    """Search transcriptions by text (case-insensitive).

    Examples:
        whisper-dictate history search "meeting"
        whisper-dictate history search "project" --limit 50
    """
    db = ctx.obj["db"]

    try:
        results = db.search_transcripts(query, limit=limit)

        if not results:
            click.echo(f"No transcriptions found matching: '{query}'")
            return

        click.echo(f"Found {len(results)} transcription(s) matching: '{query}'\n")
        click.echo(f"{'ID':<5} {'Date':<20} {'Match Preview':<55}")
        click.echo("-" * 85)

        for t in results:
            # Format timestamp
            timestamp = t.get("timestamp", "N/A")
            date_str = timestamp.split()[0] if timestamp != "N/A" else "N/A"
            time_str = (
                timestamp.split()[1][:8]
                if " " in timestamp and len(timestamp.split()) > 1
                else ""
            )

            # Highlight matching text
            text = t.get("text", "")
            # Find position of query (case-insensitive)
            lower_text = text.lower()
            lower_query = query.lower()
            pos = lower_text.find(lower_query)

            if pos >= 0:
                # Get context around the match
                start = max(0, pos - 20)
                end = min(len(text), pos + len(query) + 20)
                preview = (
                    ("..." if start > 0 else "")
                    + text[start:end]
                    + ("..." if end < len(text) else "")
                )
            else:
                preview = text[:52] + "..." if len(text) > 55 else text

            click.echo(f"{t['id']:<5} {date_str} {time_str:<10} {preview:<55}")

    except Exception as e:
        click.echo(f"Error searching transcriptions: {e}", err=True)
        sys.exit(1)


@history.command("delete")
@click.argument("transcript_id", type=int)
@click.option("--yes", "confirm_yes", is_flag=True, help="Skip confirmation prompt")
@with_database
def delete_history(ctx: click.Context, transcript_id: int, confirm_yes: bool) -> None:
    """Delete a transcription and its associated audio file.

    Examples:
        whisper-dictate history delete 42
        whisper-dictate history delete 42 --yes
    """
    from whisper_dictate.audio_storage import get_audio_storage

    db = ctx.obj["db"]
    db_config = DatabaseConfig()

    try:
        # First get the transcription to verify it exists and get audio path
        transcription = db.get_transcription_with_recording(transcript_id)

        if not transcription:
            click.echo(
                f"Error: Transcription with ID {transcript_id} not found.", err=True
            )
            sys.exit(1)

        # Show info about what will be deleted
        timestamp = transcription.get("timestamp", "N/A")
        text_preview = transcription.get("text", "")[:50]
        text_preview = (
            text_preview + "..."
            if len(transcription.get("text", "")) > 50
            else text_preview
        )

        click.echo(f"About to delete transcription #{transcript_id}:")
        click.echo(f"  Date: {timestamp}")
        click.echo(f"  Preview: {text_preview}")

        # Confirm deletion
        if not confirm_yes and not click.confirm(
            "\nAre you sure you want to delete this transcription?"
        ):
            click.echo("Deletion cancelled.")
            return

        # Delete the recording (cascades to transcript due to foreign key)
        audio_path = None
        if transcription.get("file_path"):
            audio_storage = get_audio_storage(db_config)
            audio_path = audio_storage.get_audio_path(transcription["file_path"])

        recording_id = transcription.get("recording_id")
        deleted = db.delete_recording(recording_id)

        if deleted:
            # Also delete the audio file if it exists
            if audio_path and audio_path.exists():
                audio_path.unlink()
                click.echo(f"Deleted audio file: {audio_path}")

            click.echo(f"✅ Deleted transcription #{transcript_id}")
        else:
            click.echo(
                f"Error: Failed to delete transcription #{transcript_id}", err=True
            )
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error deleting transcription: {e}", err=True)
        sys.exit(1)


@history.command("update")
@click.argument("transcript_id", type=int)
@click.option("--text", required=True, help="New transcript text")
@click.option("--language", default=None, help="New language code (optional)")
@with_database
def update_history(
    ctx: click.Context, transcript_id: int, text: str, language: str | None
) -> None:
    """Update a transcription's text and optionally language.

    Examples:
        whisper-dictate history update 123 --text "corrected transcription"
        whisper-dictate history update 123 --text "new text" --language en
    """
    db = ctx.obj["db"]

    try:
        # First get the current transcript to show old vs new
        current = db.get_transcription_with_recording(transcript_id)

        if not current:
            click.echo(
                f"Error: Transcription with ID {transcript_id} not found.", err=True
            )
            sys.exit(1)

        # Show old vs new text
        old_text = current.get("text", "")
        old_language = current.get("language")

        click.echo(f"Updating transcription #{transcript_id}:")
        click.echo("")
        click.echo("--- Current Text ---")
        click.echo(old_text[:500] + ("..." if len(old_text) > 500 else ""))
        click.echo("")
        click.echo("--- New Text ---")
        click.echo(text[:500] + ("..." if len(text) > 500 else ""))
        click.echo("")

        if old_language:
            click.echo(f"Current language: {old_language}")
        if language:
            click.echo(f"New language: {language}")
        click.echo("")

        # Confirm the update
        if not click.confirm("Do you want to proceed with this update?"):
            click.echo("Update cancelled.")
            return

        # Perform the update
        success = db.update_transcript(transcript_id, text, language)

        if success:
            click.echo(f"✅ Updated transcription #{transcript_id}")
        else:
            click.echo(
                f"Error: Failed to update transcription #{transcript_id}",
                err=True,
            )
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error updating transcription: {e}", err=True)
        sys.exit(1)


# ============ Audio Command Group ============


@click.group()
def audio() -> None:
    """Manage audio storage and perform maintenance tasks.

    This command group provides functionality to manage audio files,
    including orphaned file cleanup.
    """
    pass


@audio.command("cleanup")
@click.option(
    "--dry-run",
    is_flag=True,
    default=True,
    help="Show what would be deleted without actually deleting (default: True)",
)
@click.option(
    "--confirm",
    is_flag=True,
    default=False,
    help="Actually delete the orphaned files (default: False)",
)
@with_database
def cleanup_audio(ctx: click.Context, dry_run: bool, confirm: bool) -> None:
    """Clean up orphaned audio files not referenced in the database.

    Orphaned files are audio files that exist in the recordings directory
    but are not referenced in the database. This can happen if:
    - Database records were deleted manually
    - File system operations were performed outside the application
    - Migration issues occurred

    Examples:
        whisper-dictate audio cleanup --dry-run      # List orphaned files
        whisper-dictate audio cleanup --confirm       # Actually delete them
    """
    from whisper_dictate.audio_storage import (
        cleanup_orphaned_files,
        get_orphaned_files,
    )

    # Determine actual dry_run value
    # If --confirm is specified, dry_run becomes False
    actual_dry_run = not confirm

    try:
        # First, just get the orphaned files to display
        orphaned_files = get_orphaned_files(ctx.obj["db"])

        if not orphaned_files:
            click.echo("No orphaned audio files found.")
            return

        # Calculate total size
        total_size = sum(f["size"] for f in orphaned_files)
        total_size_mb = total_size / (1024 * 1024)

        click.echo(f"Found {len(orphaned_files)} orphaned audio file(s):")
        click.echo(f"Total size: {total_size_mb:.2f} MB ({total_size} bytes)")
        click.echo("")

        # Display each orphaned file
        for i, file_info in enumerate(orphaned_files, 1):
            size_mb = file_info["size"] / (1024 * 1024)
            click.echo(f"  {i}. {file_info['relative_path']} ({size_mb:.2f} MB)")

        click.echo("")

        if actual_dry_run:
            click.echo(
                click.style(
                    "DRY RUN: No files were deleted. "
                    "Use --confirm to actually delete these files.",
                    fg="yellow",
                )
            )
        else:
            # Perform the cleanup
            deleted_count, size_freed = cleanup_orphaned_files(
                ctx.obj["db"], dry_run=False
            )

            size_freed_mb = size_freed / (1024 * 1024)
            click.echo(
                click.style(
                    f"✅ Deleted {deleted_count} orphaned file(s), "
                    f"freed {size_freed_mb:.2f} MB",
                    fg="green",
                )
            )

    except Exception as e:
        click.echo(f"Error during audio cleanup: {e}", err=True)
        sys.exit(1)


# Register subcommands with the main cli group
cli.add_command(logs)
cli.add_command(history)
cli.add_command(audio)


# ============ Migration Command ============


@cli.command()
@click.option(
    "--force", is_flag=True, help="Force re-migration even if already completed"
)
@click.option("--status", is_flag=True, help="Check migration status only")
def migrate(force: bool, status: bool) -> None:
    """Migrate legacy state files to database.

    This command migrates legacy state files to the database:
    - ~/.whisper-dictate-state (recording state marker)
    - ~/.whisper-dictate-pid (recording process PID)

    Original files are backed up before migration.

    Examples:
        whisper-dictate migrate
        whisper-dictate migrate --force
        whisper-dictate migrate --status
    """
    from whisper_dictate.migration import (
        MigrationError,
        check_migration_status,
        run_migration,
    )

    try:
        if status:
            # Just check and display status
            result = check_migration_status()

            click.echo("Migration Status:")
            click.echo("=" * 40)

            legacy = result["legacy_files"]
            click.echo(
                f"Legacy state file:  {'Found' if legacy['state_file'] else 'Not found'}"
            )
            click.echo(
                f"Legacy PID file:   {'Found' if legacy['pid_file'] else 'Not found'}"
            )
            click.echo(
                f"Legacy audio file: {'Found' if legacy['audio_file'] else 'Not found'}"
            )

            click.echo(f"\nMigration completed: {result['migration_completed']}")
            click.echo(f"Migration needed:   {result['migration_needed']}")

            if result["migration_needed"]:
                click.echo("\nRun 'whisper-dictate migrate' to perform migration.")
            return

        # Run migration
        click.echo("Starting migration...")

        result = run_migration(force=force)

        if result.get("skipped"):
            click.echo(f"⚠️  {result['message']}")
            return

        if result["success"]:
            click.echo("✅ Migration completed successfully")
            click.echo("\nMigrated files:")
            for name, exists in result["migrated_files"].items():
                if exists:
                    click.echo(f"  • {name}")

            if result.get("backup_path"):
                click.echo(f"\nBackup saved to: {result['backup_path']}")
        else:
            click.echo("❌ Migration failed", err=True)
            sys.exit(1)

    except MigrationError as e:
        click.echo(f"❌ Migration error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
