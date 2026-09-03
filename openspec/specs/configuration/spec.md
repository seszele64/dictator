# configuration Specification

## Purpose
TBD - created by archiving change fix-provider-crash. Update Purpose after archive.
## Requirements
### Requirement: Provider environment variable resolution tolerates missing env vars
The system **SHALL** resolve the API key from the provider's declared environment variable only when that variable is a non-empty string, and **MUST NOT** pass `None` to `os.getenv` during configuration loading.

#### Scenario: Local provider declares no API key environment variable
- Given: `WHISPER_PROVIDER=local` and no API key is set in the environment
- When: `load_config()` is called
- Then: configuration loading completes without a `TypeError` and returns an `AppConfig` with an empty API key

#### Scenario: Custom provider declares no API key environment variable
- Given: `WHISPER_PROVIDER=custom` and no API key is set in the environment
- When: `load_config()` is called
- Then: configuration loading completes without a `TypeError` and returns an `AppConfig` with an empty API key

#### Scenario: Key-requiring provider resolves its declared environment variable
- Given: `WHISPER_PROVIDER=groq` and `GROQ_API_KEY` is set in the environment
- When: `load_config()` is called
- Then: the resolved `GROQ_API_KEY` value is used as the API key

---

### Requirement: Keyless local and custom providers load without an API key
The system **SHALL** accept configurations for providers that do not require authentication (`local`, `custom`) even when no API key is present, and **MUST** raise a configuration error for authentication-requiring providers (`openai`, `groq`, `together`, `deepinfra`) only when no key is available.

#### Scenario: Local provider runs without any API key
- Given: `WHISPER_PROVIDER=local` and no API key is set in the environment
- When: `load_config()` is called
- Then: configuration loading succeeds without raising a "API key not found" error

#### Scenario: Custom provider runs without any API key
- Given: `WHISPER_PROVIDER=custom`, `WHISPER_BASE_URL` is set, and no API key is set in the environment
- When: `load_config()` is called
- Then: configuration loading succeeds without raising a "API key not found" error

#### Scenario: Key-requiring provider still fails without an API key
- Given: `WHISPER_PROVIDER=openai` and no API key is set in the environment
- When: `load_config()` is called
- Then: a `ValueError` describing the missing API key is raised

---

### Requirement: Invalid provider strings fall back to custom
The system **SHALL** treat an unrecognized provider string as the `custom` provider during configuration loading so that unknown values fail gracefully instead of crashing.

#### Scenario: Unknown provider value in environment
- Given: `WHISPER_PROVIDER=not-a-real-provider` and no API key is set in the environment
- When: `load_config()` is called
- Then: the provider is treated as `custom`, configuration loading completes without an exception, and no API key is required

---

### Requirement: Regression tests cover provider configuration loading
The system **SHALL** include automated regression tests that exercise `load_config()` for every provider with and without API keys, including keyless `local`/`custom` and invalid provider strings.

#### Scenario: Parameterized load_config tests run
- Given: a test suite covering `openai`, `groq`, `together`, `deepinfra`, `local`, `custom`, and an invalid provider string with controlled environment variables
- When: the test suite is executed
- Then: keyless local/custom and invalid-provider cases pass without exceptions, and key-requiring providers without keys still raise `ValueError`
