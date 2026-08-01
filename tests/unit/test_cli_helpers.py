"""Tests for the @with_database decorator in cli_helpers.py.

These tests verify that the decorator properly:
1. Initializes the database before command execution
2. Closes the database after successful execution
3. Closes the database even when exceptions occur
4. Stores the database instance in the Click context
5. Preserves the original function's metadata (name and docstring)
"""

from unittest.mock import Mock, patch

import click
import pytest
from click.testing import CliRunner

from whisper_dictate.cli_helpers import with_database


@pytest.fixture
def mock_database():
    """Create a mock database with all required methods."""
    mock_db = Mock()
    mock_db.initialize = Mock()
    mock_db.close = Mock()
    return mock_db


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    from click.testing import CliRunner

    return CliRunner()


class TestWithDatabaseInitializes:
    """Tests for database initialization in the decorator."""

    def test_with_database_initializes_db(self, mock_database):
        """Verify decorator calls db.initialize() before command execution."""

        # Create a simple click command with the decorator
        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            # Command just succeeds
            ctx.exit(0)

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify initialize was called
            assert mock_database.initialize.called, (
                "Database initialize() was not called"
            )

    def test_with_database_gets_database_instance(self, mock_database):
        """Verify decorator gets database instance from get_database()."""

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            ctx.exit(0)

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify get_database was called with a DatabaseConfig
            mock_get_db.assert_called_once()


class TestWithDatabaseCloses:
    """Tests for database cleanup in the decorator."""

    def test_with_database_closes_db_on_success(self, mock_database):
        """Verify decorator calls db.close() after successful command execution."""

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            ctx.exit(0)

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify close was called
            assert mock_database.close.called, (
                "Database close() was not called after successful execution"
            )

    def test_with_database_closes_db_on_exception(self, mock_database):
        """Verify decorator calls db.close() even when command raises exception."""

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            raise ValueError("Test exception")

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify close was called even though exception occurred
            assert mock_database.close.called, (
                "Database close() was not called after exception"
            )

    def test_with_database_closes_db_on_click_exception(self, mock_database):
        """Verify decorator calls db.close() when Click raises an exception."""

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            # Use Click's.Abort to simulate user cancellation
            raise click.Abort()

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify close was called even on Abort
            assert mock_database.close.called, (
                "Database close() was not called after Click.Abort"
            )


class TestWithDatabaseContext:
    """Tests for context object handling in the decorator."""

    def test_with_database_stores_db_in_context(self, mock_database):
        """Verify db is stored in ctx.obj['db'] for command access."""
        stored_db = []

        # Create a parent group that initializes ctx.obj (like the real CLI does)
        @click.group()
        @click.pass_context
        def parent_group(ctx):
            ctx.ensure_object(dict)

        # Add the test command to the group
        # Note: @with_database already includes @click.pass_context,
        # so don't add it again to the decorated function
        @parent_group.command("test")
        @with_database
        def test_command(ctx):
            # Store what we get from ctx.obj['db']
            stored_db.append(ctx.obj.get("db"))
            ctx.exit(0)

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(parent_group, ["test"])

            # Verify the database was stored in context
            assert len(stored_db) == 1, "Command was not executed"
            assert stored_db[0] is mock_database, (
                f"Database was not stored in ctx.obj['db'], got: {stored_db[0]}"
            )

    def test_with_database_context_has_db_before_command(self, mock_database):
        """Verify db is available in context before the command function runs."""
        call_order = []

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            call_order.append("command")
            # Verify db is already in context at this point
            assert "db" in ctx.obj

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Ensure initialize happened before command
            assert mock_database.initialize.call_count == 1


class TestWithDatabaseMetadata:
    """Tests for metadata preservation in the decorator."""

    def test_with_database_preserves_function_name(self):
        """Verify decorator preserves the original function name."""

        # Test the decorator directly on a regular function, not a Click command
        @with_database
        def my_special_function(ctx):
            """Test function."""
            pass

        # The wrapper function should preserve the original name
        assert my_special_function.__name__ == "my_special_function"

    def test_with_database_preserves_docstring(self):
        """Verify decorator preserves the original function's docstring."""

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            """This is the original docstring."""
            ctx.exit(0)

        # Check the docstring is preserved in the callback
        assert test_command.callback.__doc__ == "This is the original docstring."

    def test_with_database_wrapper_metadata(self):
        """Verify wrapper function has same metadata as original."""

        @with_database
        def original_function(ctx):
            """Original function docstring."""
            pass

        # Verify the wrapper has the same name and docstring
        assert original_function.__name__ == "original_function"
        assert original_function.__doc__ == "Original function docstring."


class TestWithDatabaseEdgeCases:
    """Tests for edge cases in the decorator."""

    def test_with_database_close_called_once_on_success(self, mock_database):
        """Verify close is called exactly once on successful execution."""

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            ctx.exit(0)

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify close was called exactly once
            assert mock_database.close.call_count == 1

    def test_with_database_close_called_once_on_exception(self, mock_database):
        """Verify close is called exactly once even on exception."""

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            raise RuntimeError("Test error")

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify close was called exactly once
            assert mock_database.close.call_count == 1

    def test_with_database_initializes_before_close(self, mock_database):
        """Verify initialize is called before close."""
        call_sequence = []

        # Wrap methods to track call order
        original_initialize = mock_database.initialize
        original_close = mock_database.close

        def tracked_initialize():
            call_sequence.append("initialize")
            return original_initialize()

        def tracked_close():
            call_sequence.append("close")
            return original_close()

        mock_database.initialize = tracked_initialize
        mock_database.close = tracked_close

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            ctx.exit(0)

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify initialize was called before close
            assert "initialize" in call_sequence, "initialize was not called"
            assert "close" in call_sequence, "close was not called"
            assert call_sequence.index("initialize") < call_sequence.index("close"), (
                "initialize should be called before close"
            )


class TestWithDatabaseSyncMethods:
    """Tests for sync method handling in the decorator."""

    def test_with_database_calls_initialize(self, mock_database):
        """Verify the decorator calls db.initialize()."""

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            ctx.exit(0)

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify initialize is called
            assert mock_database.initialize.called

    def test_with_database_calls_close(self, mock_database):
        """Verify the decorator calls db.close()."""

        @click.command()
        @with_database
        @click.pass_context
        def test_command(ctx):
            ctx.exit(0)

        with patch("whisper_dictate.cli_helpers.get_database") as mock_get_db:
            mock_get_db.return_value = mock_database

            runner = CliRunner()
            runner.invoke(test_command)

            # Verify close is called
            assert mock_database.close.called
