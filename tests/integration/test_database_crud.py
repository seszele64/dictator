"""Group C Step 6b: Integration tests for database CRUD operations.

These are REAL SQLite integration tests - no mocking of sqlite3 or Database.
"""

import sqlite3

import pytest


class TestRecordingCRUD:
    """Tests for recording create/read/delete operations."""

    def test_create_recording_returns_id(self, real_db):
        """create_recording() returns a positive integer id."""
        recording_id = real_db.create_recording(file_path="test.wav")
        assert isinstance(recording_id, int)
        assert recording_id > 0

    def test_create_recording_with_all_fields(self, real_db):
        """All provided fields are stored and returned by get_recording()."""
        recording_id = real_db.create_recording(
            file_path="full.wav",
            duration=10.5,
            format="wav",
            sample_rate=16000,
            channels=2,
        )
        recording = real_db.get_recording(recording_id)
        assert recording is not None
        assert recording["file_path"] == "full.wav"
        assert recording["duration"] == 10.5
        assert recording["format"] == "wav"
        assert recording["sample_rate"] == 16000
        assert recording["channels"] == 2

    def test_create_recording_default_format_is_wav(self, real_db):
        """The method default format is 'wav', not the table default 'mp3'."""
        recording_id = real_db.create_recording(file_path="default.wav")
        recording = real_db.get_recording(recording_id)
        assert recording["format"] == "wav"

    def test_get_recording_returns_none_for_missing(self, real_db):
        """get_recording() returns None for a non-existent id."""
        assert real_db.get_recording(99999) is None

    def test_get_recording_has_no_updated_at_key(self, real_db):
        """The recordings table has no updated_at column, so the dict lacks the key."""
        recording_id = real_db.create_recording(file_path="noupd.wav")
        recording = real_db.get_recording(recording_id)
        assert "updated_at" not in recording

    def test_list_recordings_returns_ordered_desc(self, real_db):
        """list_recordings() returns recordings ordered by timestamp DESC."""
        real_db.execute(
            "INSERT INTO recordings (file_path, timestamp) VALUES (?, ?)",
            ("first.wav", "2020-01-01 00:00:00"),
        )
        real_db.execute(
            "INSERT INTO recordings (file_path, timestamp) VALUES (?, ?)",
            ("third.wav", "2020-01-03 00:00:00"),
        )
        real_db.execute(
            "INSERT INTO recordings (file_path, timestamp) VALUES (?, ?)",
            ("second.wav", "2020-01-02 00:00:00"),
        )
        recordings = real_db.list_recordings()
        assert [r["file_path"] for r in recordings] == [
            "third.wav",
            "second.wav",
            "first.wav",
        ]

    def test_list_recordings_pagination(self, real_db):
        """list_recordings() respects limit/offset pagination."""
        timestamps = [
            "2020-01-01 00:00:00",
            "2020-01-02 00:00:00",
            "2020-01-03 00:00:00",
            "2020-01-04 00:00:00",
            "2020-01-05 00:00:00",
        ]
        for index, timestamp in enumerate(timestamps):
            real_db.execute(
                "INSERT INTO recordings (file_path, timestamp) VALUES (?, ?)",
                (f"r{index}.wav", timestamp),
            )
        page1 = real_db.list_recordings(limit=2, offset=0)
        page2 = real_db.list_recordings(limit=2, offset=2)
        page3 = real_db.list_recordings(limit=2, offset=4)
        assert [r["file_path"] for r in page1] == ["r4.wav", "r3.wav"]
        assert [r["file_path"] for r in page2] == ["r2.wav", "r1.wav"]
        assert [r["file_path"] for r in page3] == ["r0.wav"]

    def test_delete_recording_returns_true(self, real_db):
        """delete_recording() returns True for an existing recording."""
        recording_id = real_db.create_recording(file_path="del.wav")
        assert real_db.delete_recording(recording_id) is True
        assert real_db.get_recording(recording_id) is None

    def test_delete_recording_returns_false_for_missing(self, real_db):
        """delete_recording() returns False for a non-existent recording."""
        assert real_db.delete_recording(99999) is False

    def test_delete_recording_cascades_transcripts(self, real_db):
        """Deleting a recording also deletes its transcripts (FK cascade)."""
        recording_id = real_db.create_recording(file_path="cascade.wav")
        transcript_id = real_db.create_transcript(recording_id, "attached text")
        assert real_db.delete_recording(recording_id) is True
        assert real_db.get_recording(recording_id) is None
        assert real_db.get_transcript(transcript_id) is None


class TestTranscriptCRUD:
    """Tests for transcript create/read/search/update operations."""

    def test_create_transcript_returns_id(self, real_db):
        """create_transcript() returns a positive integer id."""
        recording_id = real_db.create_recording(file_path="t.wav")
        transcript_id = real_db.create_transcript(recording_id, "hello")
        assert isinstance(transcript_id, int)
        assert transcript_id > 0

    def test_create_transcript_with_all_fields(self, real_db):
        """All provided transcript fields are stored correctly."""
        recording_id = real_db.create_recording(file_path="t2.wav")
        transcript_id = real_db.create_transcript(
            recording_id,
            "transcribed text",
            language="en",
            model_used="whisper-1",
            confidence=0.95,
        )
        transcript = real_db.get_transcript(transcript_id)
        assert transcript is not None
        assert transcript["recording_id"] == recording_id
        assert transcript["text"] == "transcribed text"
        assert transcript["language"] == "en"
        assert transcript["model_used"] == "whisper-1"
        assert transcript["confidence"] == 0.95

    def test_create_transcript_fk_violation_raises(self, real_db):
        """Creating a transcript for a missing recording raises IntegrityError."""
        with pytest.raises(sqlite3.IntegrityError):
            real_db.create_transcript(recording_id=99999, text="orphan")

    def test_get_transcript_returns_none_for_missing(self, real_db):
        """get_transcript() returns None for a non-existent id."""
        assert real_db.get_transcript(99999) is None

    def test_get_transcript_has_updated_at_key(self, real_db):
        """The transcripts table has updated_at, so the dict includes the key."""
        recording_id = real_db.create_recording(file_path="t3.wav")
        transcript_id = real_db.create_transcript(recording_id, "text")
        assert "updated_at" in real_db.get_transcript(transcript_id)

    def test_get_transcript_by_recording(self, real_db):
        """get_transcript_by_recording() returns the transcript for a recording."""
        recording_id = real_db.create_recording(file_path="byrec.wav")
        transcript_id = real_db.create_transcript(recording_id, "by recording")
        transcript = real_db.get_transcript_by_recording(recording_id)
        assert transcript is not None
        assert transcript["id"] == transcript_id
        assert transcript["text"] == "by recording"

    def test_get_transcript_by_recording_returns_none(self, real_db):
        """get_transcript_by_recording() returns None when no transcript exists."""
        recording_id = real_db.create_recording(file_path="norec.wav")
        assert real_db.get_transcript_by_recording(recording_id) is None

    def test_search_transcripts_finds_match(self, real_db):
        """search_transcripts() finds a matching transcript."""
        recording_id = real_db.create_recording(file_path="s.wav")
        real_db.create_transcript(recording_id, "hello world")
        results = real_db.search_transcripts("hello")
        assert len(results) == 1
        assert results[0]["text"] == "hello world"

    def test_search_transcripts_case_insensitive(self, real_db):
        """search_transcripts() is case-insensitive for ASCII text."""
        recording_id = real_db.create_recording(file_path="s2.wav")
        real_db.create_transcript(recording_id, "hello world")
        results = real_db.search_transcripts("HELLO")
        assert len(results) == 1
        assert results[0]["text"] == "hello world"

    def test_search_transcripts_empty_query_matches_all(self, real_db):
        """search_transcripts('') returns all transcripts."""
        recording_id = real_db.create_recording(file_path="s3.wav")
        real_db.create_transcript(recording_id, "first")
        real_db.create_transcript(recording_id, "second")
        results = real_db.search_transcripts("")
        assert len(results) == 2

    def test_search_transcripts_no_match(self, real_db):
        """search_transcripts() returns an empty list when nothing matches."""
        recording_id = real_db.create_recording(file_path="s4.wav")
        real_db.create_transcript(recording_id, "hello world")
        assert real_db.search_transcripts("nonexistent") == []

    def test_search_transcripts_includes_recording_fields(self, real_db):
        """Search results include file_path, recording_timestamp and duration from the JOIN."""
        recording_id = real_db.create_recording(file_path="join.wav", duration=5.5)
        real_db.create_transcript(recording_id, "hello world")
        result = real_db.search_transcripts("hello")[0]
        assert result["file_path"] == "join.wav"
        assert result["recording_timestamp"] is not None
        assert result["duration"] == 5.5

    def test_list_transcriptions_with_date_filter(self, real_db):
        """list_transcriptions(date=...) returns only transcripts on that date."""
        recording_id = real_db.create_recording(file_path="d.wav")
        real_db.execute(
            "INSERT INTO transcripts (recording_id, text, timestamp) VALUES (?, ?, ?)",
            (recording_id, "day one", "2020-01-01 10:00:00"),
        )
        real_db.execute(
            "INSERT INTO transcripts (recording_id, text, timestamp) VALUES (?, ?, ?)",
            (recording_id, "day two", "2020-01-02 10:00:00"),
        )
        results = real_db.list_transcriptions(date="2020-01-01")
        assert [t["text"] for t in results] == ["day one"]

    def test_list_transcriptions_no_date_returns_all(self, real_db):
        """Without a date filter, all transcripts are returned ordered by timestamp DESC."""
        recording_id = real_db.create_recording(file_path="d2.wav")
        real_db.execute(
            "INSERT INTO transcripts (recording_id, text, timestamp) VALUES (?, ?, ?)",
            (recording_id, "day one", "2020-01-01 10:00:00"),
        )
        real_db.execute(
            "INSERT INTO transcripts (recording_id, text, timestamp) VALUES (?, ?, ?)",
            (recording_id, "day two", "2020-01-02 10:00:00"),
        )
        results = real_db.list_transcriptions()
        assert [t["text"] for t in results] == ["day two", "day one"]

    def test_get_transcription_with_recording(self, real_db):
        """get_transcription_with_recording() returns a joined dict."""
        recording_id = real_db.create_recording(file_path="g.wav", duration=3.5)
        transcript_id = real_db.create_transcript(recording_id, "joined")
        result = real_db.get_transcription_with_recording(transcript_id)
        assert result is not None
        assert result["id"] == transcript_id
        assert result["recording_id"] == recording_id
        assert result["text"] == "joined"
        assert result["file_path"] == "g.wav"
        assert result["recording_timestamp"] is not None
        assert result["duration"] == 3.5

    def test_get_transcription_with_recording_returns_none(self, real_db):
        """get_transcription_with_recording() returns None for a missing transcript."""
        assert real_db.get_transcription_with_recording(99999) is None

    def test_update_transcript_text(self, real_db):
        """update_transcript() changes the text and bumps updated_at."""
        recording_id = real_db.create_recording(file_path="u.wav")
        transcript_id = real_db.create_transcript(recording_id, "original")
        # Backdate created_at/updated_at so the change is detectable even
        # when the update happens within the same second.
        real_db.execute(
            "UPDATE transcripts SET created_at = '2020-01-01 00:00:00', "
            "updated_at = '2020-01-01 00:00:00' WHERE id = ?",
            (transcript_id,),
        )
        assert real_db.update_transcript(transcript_id, "updated text") is True
        transcript = real_db.get_transcript(transcript_id)
        assert transcript["text"] == "updated text"
        assert transcript["updated_at"] != "2020-01-01 00:00:00"

    def test_update_transcript_text_and_language(self, real_db):
        """update_transcript() can update text and language together."""
        recording_id = real_db.create_recording(file_path="u2.wav")
        transcript_id = real_db.create_transcript(recording_id, "original", language="en")
        assert (
            real_db.update_transcript(transcript_id, "nuevo texto", language="es")
            is True
        )
        transcript = real_db.get_transcript(transcript_id)
        assert transcript["text"] == "nuevo texto"
        assert transcript["language"] == "es"

    def test_update_transcript_returns_false_for_missing(self, real_db):
        """update_transcript() returns False for a non-existent transcript."""
        assert real_db.update_transcript(99999, "text") is False

    def test_update_transcript_language_none_preserves_existing(self, real_db):
        """update_transcript() with language=None leaves the existing language unchanged."""
        recording_id = real_db.create_recording(file_path="u3.wav")
        transcript_id = real_db.create_transcript(recording_id, "hola", language="es")
        assert real_db.update_transcript(transcript_id, "hola mundo") is True
        assert real_db.get_transcript(transcript_id)["language"] == "es"


class TestLogCRUD:
    """Tests for log create/query/cleanup operations."""

    def test_create_log_returns_id(self, real_db):
        """create_log() returns a positive integer id."""
        log_id = real_db.create_log("INFO", "test message")
        assert isinstance(log_id, int)
        assert log_id > 0

    def test_create_log_with_source_and_metadata(self, real_db):
        """Logs store source and metadata correctly."""
        real_db.create_log("INFO", "with meta", source="test_module", metadata={"a": 1})
        log = real_db.query_logs()[0]
        assert log["source"] == "test_module"
        assert log["message"] == "with meta"

    def test_create_log_metadata_json_is_string(self, real_db):
        """query_logs() returns metadata_json as a STRING, not a parsed dict."""
        real_db.create_log("INFO", "with meta", source="s", metadata={"key": "value"})
        result = real_db.query_logs()[0]
        assert isinstance(result["metadata_json"], str)

    def test_create_log_without_metadata(self, real_db):
        """metadata_json is None when no metadata is provided."""
        real_db.create_log("INFO", "no meta")
        result = real_db.query_logs()[0]
        assert result["metadata_json"] is None

    def test_query_logs_returns_all_when_no_filters(self, real_db):
        """query_logs() returns all logs when no filters are given."""
        real_db.create_log("INFO", "one")
        real_db.create_log("INFO", "two")
        real_db.create_log("INFO", "three")
        logs = real_db.query_logs()
        assert len(logs) == 3

    def test_query_logs_filter_by_level(self, real_db):
        """query_logs(level='info') filters by level (the query uppercases it)."""
        real_db.create_log("INFO", "info message")
        real_db.create_log("ERROR", "error message")
        logs = real_db.query_logs(level="info")
        assert len(logs) == 1
        assert logs[0]["level"] == "INFO"
        assert logs[0]["message"] == "info message"

    def test_query_logs_filter_by_source(self, real_db):
        """query_logs(source=...) returns only logs from that source."""
        real_db.create_log("INFO", "from module a", source="module_a")
        real_db.create_log("INFO", "from module b", source="module_b")
        logs = real_db.query_logs(source="module_a")
        assert len(logs) == 1
        assert logs[0]["source"] == "module_a"

    def test_query_logs_filter_by_time_range(self, real_db):
        """query_logs(from_time=..., to_time=...) filters by ISO timestamps."""
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "before", "2020-01-01 00:00:00"),
        )
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "inside", "2021-06-15 12:00:00"),
        )
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "after", "2022-06-15 12:00:00"),
        )
        logs = real_db.query_logs(
            from_time="2021-01-01 00:00:00", to_time="2021-12-31 23:59:59"
        )
        assert [log["message"] for log in logs] == ["inside"]

    def test_query_logs_ordered_desc(self, real_db):
        """query_logs() results are ordered by timestamp DESC."""
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "first", "2020-01-01 00:00:00"),
        )
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "third", "2020-01-03 00:00:00"),
        )
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "second", "2020-01-02 00:00:00"),
        )
        logs = real_db.query_logs()
        assert [log["message"] for log in logs] == ["third", "second", "first"]

    def test_query_logs_respects_limit(self, real_db):
        """query_logs(limit=...) returns at most the requested number of logs."""
        for index in range(5):
            real_db.create_log("INFO", f"msg {index}")
        assert len(real_db.query_logs(limit=3)) == 3

    def test_cleanup_old_logs_deletes_old(self, real_db):
        """cleanup_old_logs() deletes logs older than the retention period."""
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "old", "2020-01-01 00:00:00"),
        )
        deleted = real_db.cleanup_old_logs(retention_days=1)
        assert deleted == 1
        assert real_db.query_logs() == []

    def test_cleanup_old_logs_keeps_recent(self, real_db):
        """cleanup_old_logs() keeps logs within the retention period."""
        real_db.execute(
            "INSERT INTO logs (level, message, timestamp) VALUES (?, ?, ?)",
            ("INFO", "old", "2020-01-01 00:00:00"),
        )
        real_db.create_log("INFO", "recent")
        deleted = real_db.cleanup_old_logs(retention_days=1)
        assert deleted == 1
        remaining = real_db.query_logs()
        assert len(remaining) == 1
        assert remaining[0]["message"] == "recent"

    def test_cleanup_old_logs_returns_zero_when_nothing_deleted(self, real_db):
        """cleanup_old_logs() returns 0 when nothing is old enough to delete."""
        real_db.create_log("INFO", "recent one")
        real_db.create_log("ERROR", "recent two")
        assert real_db.cleanup_old_logs(retention_days=1) == 0


class TestStateCRUD:
    """Tests for the key-value state operations."""

    def test_set_and_get_state_string(self, real_db):
        """String state values round-trip."""
        real_db.set_state("key", "value")
        assert real_db.get_state("key") == "value"

    def test_set_and_get_state_dict(self, real_db):
        """Dict state values round-trip via JSON."""
        real_db.set_state("dict", {"a": 1, "b": [2, 3]})
        assert real_db.get_state("dict") == {"a": 1, "b": [2, 3]}

    def test_set_and_get_state_list(self, real_db):
        """List state values round-trip via JSON."""
        real_db.set_state("list", [1, 2, 3])
        assert real_db.get_state("list") == [1, 2, 3]

    def test_set_and_get_state_int(self, real_db):
        """Int state values round-trip via JSON."""
        real_db.set_state("int", 42)
        assert real_db.get_state("int") == 42

    def test_set_state_upsert(self, real_db):
        """Setting the same key twice updates the value (upsert)."""
        real_db.set_state("key", "first")
        real_db.set_state("key", "second")
        assert real_db.get_state("key") == "second"

    def test_get_state_returns_none_for_missing(self, real_db):
        """get_state() returns None for a non-existent key."""
        assert real_db.get_state("nonexistent") is None

    def test_delete_state_returns_true(self, real_db):
        """delete_state() returns True for an existing key."""
        real_db.set_state("key", "value")
        assert real_db.delete_state("key") is True
        assert real_db.get_state("key") is None

    def test_delete_state_returns_false_for_missing(self, real_db):
        """delete_state() returns False for a non-existent key."""
        assert real_db.delete_state("nonexistent") is False

    def test_set_state_non_serializable_raises_typeerror(self, real_db):
        """set_state() raises TypeError for non-JSON-serializable values."""
        with pytest.raises(TypeError):
            real_db.set_state("key", object())
