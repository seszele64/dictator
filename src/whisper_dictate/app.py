"""Application composition root.

WHY THIS EXISTS: Application startup needs one place that assembles the
environment (``.env`` loading) and configuration before anything else runs.
Previously each entry point called ``load_config()`` directly, which hid the
``load_dotenv()`` side effect inside the config module; this module makes the
bootstrap sequence explicit and gives future composition work (per-command
Database/AudioStorage construction, S2) a single seam.

RESPONSIBILITY: Bootstrap the application: load .env, then load and validate
configuration.
BOUNDARIES:
- DOES: Load .env into os.environ, load AppConfig from the environment
- DOES NOT: Construct Database/AudioStorage instances or touch the filesystem
  beyond reading .env
"""

from dotenv import load_dotenv

from whisper_dictate.config import AppConfig, load_config


def bootstrap(require_api_key: bool = False) -> AppConfig:
    """Load the application environment and configuration.

    This is the composition root entry point: every application entry point
    (CLI group callback, toggle script) starts here.

    WHY load_dotenv lives HERE and not in load_config(): importing
    ``whisper_dictate.config`` must stay side-effect-free (no os.environ
    mutation) so tests can import the module in a pristine environment;
    bootstrap is the explicit, opt-in step that mutates the process
    environment from ``.env`` before configuration is read.

    Args:
        require_api_key: When True, raise ValueError if the configured
            provider declares an auth env var but no key is available.
            Entry points for database-only commands pass False and validate
            the key lazily on transcription paths instead.

    Returns:
        AppConfig: Validated application configuration.

    Raises:
        ValueError: If required configuration is missing (see validate_api_key()).
    """
    load_dotenv()
    return load_config(require_api_key=require_api_key)
