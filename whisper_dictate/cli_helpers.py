"""Helper functions and decorators for CLI commands."""

import functools

import click

from whisper_dictate.config import DatabaseConfig
from whisper_dictate.database import Database


def with_database(f):
    """Decorator that provides a fresh, per-invocation Database instance.

    Constructs a new Database from the configuration loaded by the CLI group
    callback (so user-configured database paths and settings are honored),
    initializes it, stashes it in ``ctx.obj["db"]``, and closes it when the
    command returns - on success or on any exception.

    WHY a fresh instance per invocation instead of a module-level singleton:
    a shared global couples every command to hidden mutable state, leaks its
    configuration to whatever calls it first, and made close-on-exit
    asymmetric (``close()`` vs ``close_database()``). A per-invocation
    instance has exactly one owner: this decorator.

    Patch seam for tests: patch ``whisper_dictate.cli_helpers.Database`` (the
    constructor used inside the decorator), not a module-level getter.
    """

    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        # Prefer the configuration loaded by the CLI group callback
        db_config = None
        if isinstance(ctx.obj, dict):
            config = ctx.obj.get("config")
            db_config = getattr(config, "database", None)
        if db_config is None:
            # Standalone usage outside the CLI group (tools, direct tests)
            db_config = DatabaseConfig()

        # Construct and initialize a dedicated database for this invocation.
        # Construction is trivial (no I/O); initialization happens INSIDE the
        # try so a failed initialize still closes whatever was opened (S1).
        db = Database(db_config)

        try:
            db.initialize()

            ctx.obj = ctx.obj or {}
            ctx.obj["db"] = db

            # Invoke the command
            return ctx.invoke(f, ctx, *args, **kwargs)
        finally:
            # Close database - always, even when the command raises
            db.close()

    return wrapper
