"""Helper functions and decorators for CLI commands."""

import click

from whisper_dictate.config import DatabaseConfig
from whisper_dictate.database import get_database


def with_database(f):
    """Decorator that handles database initialization and cleanup.

    Uses the database configuration loaded by the CLI group callback so that
    user-configured database paths and settings are honored instead of
    silently falling back to defaults.
    """

    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        # Prefer the configuration loaded by the CLI group callback
        db_config = None
        if isinstance(ctx.obj, dict):
            config = ctx.obj.get("config")
            db_config = getattr(config, "database", None)
        if db_config is None:
            # Standalone usage outside the CLI group (tools, direct tests)
            db_config = DatabaseConfig()

        # Initialize database
        db = get_database(db_config)
        db.initialize()

        ctx.obj = ctx.obj or {}
        ctx.obj["db"] = db

        try:
            # Invoke the command
            return ctx.invoke(f, ctx, *args, **kwargs)
        finally:
            # Close database
            db.close()

    # Preserve function metadata
    wrapper.__name__ = f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper
