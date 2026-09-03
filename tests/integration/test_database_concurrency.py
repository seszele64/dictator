"""Integration tests for database concurrency and thread safety.

These tests verify that the Database class supports cross-thread access
after the concurrency fix (check_same_thread=False + RLock + lock-guarded
initialize/close). The threading.RLock serializes all connection access,
and initialize()/close() are protected against concurrent modification.
"""

import queue
import threading

from whisper_dictate.database import Database


class TestThreadSafeDatabase:
    """Tests verifying cross-thread database access after the concurrency fix."""

    def test_cross_thread_use_works_after_fix(self, real_db_config):
        """Cross-thread database access works after the concurrency fix.

        The fix adds check_same_thread=False to sqlite3.connect() and uses
        threading.RLock to serialize access. A thread other than the one that
        created the connection can now safely use it, because:
        1. check_same_thread=False removes the C-level thread-affinity gate
        2. RLock serializes all connection access through connection()/transaction()
        3. initialize()/close() are now lock-guarded
        """
        db = Database(real_db_config)
        db.initialize()
        try:
            results = queue.Queue()

            def use_from_thread():
                try:
                    row = db.execute("SELECT 1")
                    results.put(row.fetchone())
                except Exception as e:  # noqa: BLE001 - capture any error for assertion
                    results.put(e)

            t = threading.Thread(target=use_from_thread)
            t.start()
            t.join()

            result = results.get(timeout=5)
            assert not isinstance(result, Exception), f"Cross-thread use failed: {result}"
            assert result == (1,)
        finally:
            db.close()

    def test_same_thread_use_works(self, real_db_config):
        """The thread that created the connection can use it normally."""
        db = Database(real_db_config)
        try:
            db.initialize()
            assert db.execute("SELECT 1").fetchone() == (1,)
        finally:
            db.close()

    def test_lock_serializes_cross_thread_access(self, real_db_config):
        """The RLock serializes cross-thread database access.

        Three threads each perform a database operation; the RLock ensures
        they don't interfere. All operations complete successfully.
        """
        db = Database(real_db_config)
        db.initialize()
        try:
            errors = queue.Queue()

            def write_from_thread(label):
                try:
                    db.execute(
                        "INSERT INTO recordings (file_path) VALUES (?)",
                        (f"thread-{label}.wav",),
                    )
                    errors.put(None)
                except Exception as e:  # noqa: BLE001 - capture any error for assertion
                    errors.put(e)

            threads = [threading.Thread(target=write_from_thread, args=(i,)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            for _ in range(3):
                assert errors.get(timeout=5) is None

            # All 3 recordings were inserted
            count = db.fetchone("SELECT COUNT(*) FROM recordings WHERE file_path LIKE 'thread-%'")[0]
            assert count == 3
        finally:
            db.close()

    def test_reentrant_transaction_path_works(self, real_db):
        """Reentrant lock acquisition inside transaction() works with RLock.

        This is a regression test for a latent self-deadlock: calling a public
        DB method (which acquires the lock via connection()) inside a
        transaction() block (which also holds the lock) deadlocks with a
        non-reentrant Lock. The RLock allows reentrant acquisition by the
        same thread, so this pattern works.

        The migration.py module uses this exact pattern:
            with db.transaction():
                db.set_state(...)
        """
        with real_db.transaction() as conn:
            conn.execute("INSERT INTO recordings (file_path) VALUES (?)", ("reentrant.wav",))
            # Calling a public method inside transaction() acquires the
            # RLock reentrantly — this would deadlock with a plain Lock
            real_db.set_state("migration_status", "in_progress")

        # Verify both operations committed
        row = real_db.fetchone("SELECT id FROM recordings WHERE file_path = ?", ("reentrant.wav",))
        assert row is not None
        assert real_db.get_state("migration_status") == "in_progress"

    def test_sequential_operations_work(self, real_db_config):
        """Sequential operations on one thread work with the RLock.

        The RLock is reentrant, and each db method acquires it via
        connection()/transaction() and releases before returning, so a
        sequence of operations on the same thread runs fine and is
        serialized against any other thread.
        """
        db = Database(real_db_config)
        try:
            db.initialize()
            recording_id = db.create_recording(file_path="ser.wav")
            db.create_transcript(recording_id, "serialized text")
            recordings = db.list_recordings()
            assert any(r["id"] == recording_id for r in recordings)
            assert db.delete_recording(recording_id) is True
            assert db.get_recording(recording_id) is None
        finally:
            db.close()

    def test_execute_result_survives_later_statements_and_close(self, real_db_config):
        """CursorResult from execute() remains valid after later statements and close().

        This verifies the materialized-result fix: the result holds no live
        sqlite3 cursor, so it can be consumed after the lock is released,
        after other statements run, and even after the database is closed.
        """
        db = Database(real_db_config)
        db.initialize()
        result = db.execute("SELECT 1")
        # Run another statement (would interleave with a live cursor)
        db.execute("SELECT 2")
        # The first result is still valid
        assert result.fetchone() == (1,)
        db.close()
        # Even after close(), the materialized result is readable
        assert result.fetchone() is None  # already consumed, returns None
