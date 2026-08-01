"""Helper functions and decorators for CLI commands."""

import click

from whisper_dictate.config import DatabaseConfig
from whisper_dictate.database import get_database


def with_database(f):
    """Decorator that handles database initialization and cleanup."""

    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        # Initialize database
        db_config = DatabaseConfig()
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
