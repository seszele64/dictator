"""Test configuration and fixtures for whisper-dictate."""

import atexit
import contextlib
import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from whisper_dictate.config import (  # noqa: E402
    AppConfig,
    AudioConfig,
    DatabaseConfig,
    OpenAIConfig,
)
from whisper_dictate.transcription import TranscriptionResult  # noqa: E402

# Add project root to path for toggle_dictate module
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session", autouse=True)
def mock_cli_setup():
    """Prevent CLI from initializing real database during tests."""
    os.environ["OPENAI_API_KEY"] = "test-api-key"

    with (
        patch("whisper_dictate.cli.setup_logging") as mock_setup_logging,
        patch("whisper_dictate.cli.load_config") as mock_load_config,
    ):
        mock_setup_logging.return_value = None

        mock_config = Mock()
        mock_config.openai.api_key = "test-api-key"
        mock_config.openai.provider = "openai"
        mock_config.openai.base_url = None
        mock_config.openai.model = "whisper-1"
        mock_config.openai.timeout = 30.0
        mock_config.openai.language = None
        mock_config.openai.temperature = 0.0
        mock_config.audio.sample_rate = 16000
        mock_config.audio.channels = 1
        mock_config.audio.duration = 1.0
        mock_config.audio.device = None
        mock_config.audio.mp3_enabled = False
        mock_config.log_level = "DEBUG"
        mock_config.copy_to_clipboard = True
        mock_load_config.return_value = mock_config

        yield


# Session-scoped fixture to patch sounddevice/soundfile/pydub before any imports
# This must run BEFORE any other fixtures to prevent the real modules from loading
@pytest.fixture(scope="session", autouse=True)
def patch_audio_modules():
    """Patch sounddevice, soundfile, and pydub modules in sys.modules before any imports.

    This prevents the real audio libraries from being loaded at module import time,
    which can cause hangs when no audio device is available.
    """
    # Create mock modules
    mock_sd = Mock()
    mock_sf = Mock()
    mock_pydub = Mock()
    mock_audio_segment = Mock()
    mock_pydub.AudioSegment = mock_audio_segment

    # Configure mock sounddevice
    mock_sd.rec = Mock()
    mock_sd.wait = Mock(return_value=None)
    mock_sd.query_devices = Mock(
        return_value=[
            {"name": "default", "max_input_channels": 2},
            {"name": "pulse", "max_input_channels": 2},
        ]
    )
    mock_sd.PortAudioError = Exception
    mock_sd.stop = Mock()

    # Configure mock soundfile
    mock_sf.write = Mock()

    # Store original modules if they exist
    original_sd = sys.modules.get("sounddevice")
    original_sf = sys.modules.get("soundfile")
    original_pydub = sys.modules.get("pydub")

    # Patch sys.modules
    sys.modules["sounddevice"] = mock_sd
    sys.modules["soundfile"] = mock_sf
    sys.modules["pydub"] = mock_pydub

    yield

    # Restore original modules
    if original_sd is not None:
        sys.modules["sounddevice"] = original_sd
    else:
        sys.modules.pop("sounddevice", None)

    if original_sf is not None:
        sys.modules["soundfile"] = original_sf
    else:
        sys.modules.pop("soundfile", None)

    if original_pydub is not None:
        sys.modules["pydub"] = original_pydub
    else:
        sys.modules.pop("pydub", None)


# Ensure sounddevice cleanup on exit
def _cleanup_sounddevice():
    try:
        import sounddevice as sd

        sd.stop()
    except Exception:
        pass


atexit.register(_cleanup_sounddevice)


@pytest.fixture(autouse=True)
def reset_persistent_notification_state():
    """Reset PersistentNotification class variables before each test."""
    import whisper_dictate.notifications as notifications_module

    # Store original values
    original_time = notifications_module.PersistentNotification._last_operation_time
    original_recording = notifications_module._recording_notification

    # Apply patch with explicit control
    patcher = patch.object(notifications_module, "is_dunst_running", return_value=True)
    patcher.start()

    notifications_module.PersistentNotification._last_operation_time = 0.0
    notifications_module._recording_notification = None

    yield

    # Explicit cleanup
    patcher.stop()
    notifications_module.PersistentNotification._last_operation_time = original_time
    notifications_module._recording_notification = original_recording


@pytest.fixture
def temp_audio_file() -> Generator[Path, None, None]:
    """Create a temporary audio file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        # Create minimal WAV file header for testing
        wav_header = (
            b"RIFF\x26\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00"
            b"\x00}\x00\x00\x02\x00\x10\x00data\x02\x00\x00\x00\x00\x00"
        )
        tmp.write(wav_header)
        tmp.flush()
        yield Path(tmp.name)
    # Cleanup
    with contextlib.suppress(OSError):
        os.unlink(tmp.name)


@pytest.fixture
def mock_config() -> AppConfig:
    """Create a mock configuration for testing."""
    return AppConfig(
        audio=AudioConfig(
            sample_rate=16000,
            channels=1,
            duration=1.0,  # Short duration for tests
            device=None,
            mp3_enabled=False,  # Default to disabled for backward compatibility
            mp3_bitrate="128k",
            keep_wav=False,
        ),
        openai=OpenAIConfig(
            api_key="test-api-key",
            model="whisper-1",
            timeout=10.0,
            silence_threshold_dbfs=-50.0,
            task=None,
        ),
        log_level="DEBUG",
        copy_to_clipboard=True,
    )


@pytest.fixture
def mock_config_mp3_enabled() -> AppConfig:
    """Create a mock configuration with MP3 enabled for testing."""
    return AppConfig(
        audio=AudioConfig(
            sample_rate=16000,
            channels=1,
            duration=1.0,
            device=None,
            mp3_enabled=True,
            mp3_bitrate="128k",
            keep_wav=False,
        ),
        openai=OpenAIConfig(
            api_key="test-api-key",
            model="whisper-1",
            timeout=10.0,
            silence_threshold_dbfs=-50.0,
            task=None,
        ),
        log_level="DEBUG",
        copy_to_clipboard=True,
    )


@pytest.fixture
def mock_config_mp3_keep_wav() -> AppConfig:
    """Create a mock configuration with MP3 enabled and keep_wav=True."""
    return AppConfig(
        audio=AudioConfig(
            sample_rate=16000,
            channels=1,
            duration=1.0,
            device=None,
            mp3_enabled=True,
            mp3_bitrate="128k",
            keep_wav=True,
        ),
        openai=OpenAIConfig(
            api_key="test-api-key",
            model="whisper-1",
            timeout=10.0,
            silence_threshold_dbfs=-50.0,
            task=None,
        ),
        log_level="DEBUG",
        copy_to_clipboard=True,
    )


@pytest.fixture
def mock_transcription_result() -> TranscriptionResult:
    """Create a mock transcription result for testing."""
    return TranscriptionResult(text="This is a test transcription.", language="en")


@pytest.fixture
def mock_silent_transcription_result() -> TranscriptionResult:
    """Create a mock silent transcription result for testing."""
    return TranscriptionResult(text="", silence_detected=True)


@pytest.fixture
def mock_openai_client() -> Generator[Mock, None, None]:
    """Mock OpenAI client for testing transcription."""
    with patch("openai.OpenAI") as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock successful transcription response
        mock_response = Mock()
        mock_response.text = "This is a test transcription."
        mock_response.language = "en"
        mock_client.audio.transcriptions.create.return_value = mock_response

        yield mock_client


@pytest.fixture
def mock_subprocess() -> Generator[Mock, None, None]:
    """Mock subprocess for testing clipboard and notifications."""
    with patch("subprocess.run") as mock_run:
        # Default successful response
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "mock output"
        mock_run.return_value.stderr = ""
        yield mock_run


@pytest.fixture
def mock_sounddevice() -> Generator[dict[str, Mock], None, None]:
    """Mock sounddevice for testing audio recording."""
    with (
        patch("sounddevice.rec") as mock_rec,
        patch("sounddevice.wait") as mock_wait,
        patch("sounddevice.query_devices") as mock_query,
    ):
        # Mock successful recording
        mock_rec.return_value = [[0.1], [0.2], [0.3]]  # Mock audio data
        mock_wait.return_value = None

        # Mock device query
        mock_query.return_value = [
            {"name": "default", "max_input_channels": 2},
            {"name": "pulse", "max_input_channels": 2},
        ]

        yield {"rec": mock_rec, "wait": mock_wait, "query": mock_query}


@pytest.fixture
def mock_soundfile() -> Generator[Mock, None, None]:
    """Mock soundfile for testing audio file operations."""
    with patch("soundfile.write") as mock_write:
        mock_write.return_value = None
        yield mock_write


@pytest.fixture
def temp_env_vars() -> Generator[None, None, None]:
    """Set up temporary environment variables for testing."""
    original_env = dict(os.environ)

    # Set test environment variables
    os.environ["OPENAI_API_KEY"] = "test-api-key"

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def database():
    """Provide a mock database with proper lifecycle tracking.

    This fixture provides a mock database that:
    - Has all common methods as Mocks
    - Tracks whether close() was called
    - Can be used to verify proper cleanup
    """
    mock_db = Mock()
    mock_db.initialize = Mock()
    mock_db.close = Mock()
    mock_db.query_logs = Mock(return_value=[])
    mock_db.cleanup_old_logs = Mock(return_value=0)
    mock_db.list_transcriptions = Mock(return_value=[])
    mock_db.get_transcription_with_recording = Mock(return_value=None)
    mock_db.search_transcripts = Mock(return_value=[])
    mock_db.delete_recording = Mock(return_value=False)
    mock_db.update_transcript = Mock(return_value=False)
    return mock_db


@pytest.fixture
def db_singleton_reset():
    """Reset module-level Database and AudioStorage singletons before and after test."""
    import whisper_dictate.audio_storage as storage_mod
    import whisper_dictate.database as db_mod

    # Reset before
    db_mod._database = None
    storage_mod._audio_storage = None

    yield

    # Clean up any instances created during the test
    if db_mod._database is not None:
        with contextlib.suppress(Exception):
            db_mod._database.close()
        db_mod._database = None
    if storage_mod._audio_storage is not None:
        storage_mod._audio_storage = None


@pytest.fixture
def real_db_config(tmp_path) -> DatabaseConfig:
    """Create a DatabaseConfig pointing to temp directories."""
    return DatabaseConfig(
        path=tmp_path / "test.db",
        recordings_path=tmp_path / "recordings",
    )


@pytest.fixture
def real_db(real_db_config, db_singleton_reset):
    """Create a real Database instance with a temp SQLite file, auto-initialized and closed."""
    from whisper_dictate.database import Database

    db = Database(real_db_config)
    db.initialize()
    yield db
    with contextlib.suppress(Exception):
        db.close()


@pytest.fixture
def env_isolator(tmp_path, monkeypatch):
    """Isolate environment variables: redirect XDG dirs, set test API key, clear WHISPER_* vars."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    # Clear any WHISPER_* env vars that might affect config loading
    for key in list(os.environ.keys()):
        if key.startswith("WHISPER_"):
            monkeypatch.delenv(key, raising=False)
    yield tmp_path


@pytest.fixture
def tmp_recordings_dir(tmp_path):
    """Create a temporary recordings directory."""
    recordings = tmp_path / "recordings"
    recordings.mkdir(parents=True, exist_ok=True)
    yield recordings
