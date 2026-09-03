# Test Infrastructure Specification

## Purpose

This specification defines the test infrastructure for the whisper-dictate project. The test infrastructure ensures reliable, non-hanging test execution through proper test organization, real-database integration testing, comprehensive state isolation, coverage collection, and per-module coverage gates.

### Background

The project uses Python's `sqlite3` for persistence, `soundfile` for audio handling, and subprocess-based audio capture. Testing requires careful management of database singletons, filesystem paths, and module-level state to prevent test interference. This specification establishes standardized patterns for writing and running tests that are reliable, maintainable, and verifiable through coverage gates.

### Scope

This specification covers:
- Test directory organization (unit/, integration/, contract/, e2e/)
- Shared real-database test fixtures with automatic cleanup
- Environment isolation (XDG directories, API keys, config paths)
- Coverage collection in CI using pytest-cov
- Per-module coverage thresholds enforced in CI
- Real SQLite integration tests (schema, CRUD, transactions, FK cascade, maintenance)
- Provider contract tests (ABC conformance, error wrapping, parameter forwarding)
- Audio storage filesystem tests (real FS operations in temp directories)
- Database logging tests (DatabaseLogHandler with real database)
- Migration tests (detect, run, rollback, verify)
- End-to-end dictation pipeline tests (real SQLite + storage, mocked audio/API/clipboard)

## Requirements

### Requirement: Coverage Collection in CI
**SHALL** collect test coverage using pytest-cov on every CI run and report per-module coverage without enforcing thresholds initially.

#### Scenario: CI runs coverage
- Given: a pull request is opened against main
- When: the CI test job runs
- Then: pytest executes with `--cov=whisper_dictate --cov-report=term-missing` and coverage data is collected

#### Scenario: Coverage dependency declared
- Given: the project dev dependencies are installed
- When: `uv sync --extra dev` is executed
- Then: pytest-cov is available as a development dependency

### Requirement: Test Directory Organization
**SHALL** organize tests into unit/, integration/, contract/, and e2e/ subdirectories reflecting test scope and boundary.

#### Scenario: Flat tests reorganized
- Given: the existing flat tests/ directory with all test files at root
- When: the reorganization is complete
- Then: unit tests are in tests/unit/, integration tests in tests/integration/, contract tests in tests/contract/, and e2e tests in tests/e2e/
- And: contract tests cover the provider seam (ABC conformance, provider construction/properties, error wrapping, parameter forwarding, task routing, factory selection) in `tests/contract/test_openai_compatible.py`, while TranscriptionResult and TranscriptionError unit tests stay in `tests/unit/`

#### Scenario: All tests still pass after reorganization
- Given: the test directory has been reorganized
- When: `uv run pytest` is executed
- Then: all 258 previously passing tests still pass with no collection errors

### Requirement: Shared Real-Database Test Fixtures
**SHALL** provide function-scoped fixtures that create real SQLite databases in temporary directories for integration tests, with automatic cleanup.

#### Scenario: Real database fixture
- Given: a test requests the real_db fixture
- When: the fixture is activated
- Then: a real Database instance is created with a temp-dir SQLite file and is automatically closed and cleaned up after the test

#### Scenario: Environment isolation
- Given: a test requests the env_isolator fixture
- When: the fixture is activated
- Then: XDG directories, API keys, and config paths are redirected to temp directories and restored after the test

### Requirement: Per-Module Coverage Gates
**SHALL** enforce minimum coverage thresholds per module in CI after all tests are written.

#### Scenario: Coverage gate enforced
- Given: all Phase 2 tests are written and committed
- When: CI runs the coverage check
- Then: database.py coverage MUST be >= 70%, config.py >= 80%, db_logging.py >= 60%, migration.py >= 50%, audio_storage.py >= 80%, providers/openai_compatible.py >= 80%

### Requirement: Real SQLite Integration Tests
**SHALL** test database.py against a real SQLite database (not mocks) covering schema initialization, migrations, CRUD operations, transactions, FK cascade, and maintenance.

#### Scenario: Schema initialization
- Given: a fresh temporary directory
- When: Database.initialize() is called
- Then: the schema is created with the correct version, PRAGMAs are set, and tables exist

#### Scenario: CRUD operations
- Given: an initialized real database
- When: recordings, transcripts, and logs are created, queried, updated, and deleted
- Then: all operations succeed with correct data round-trip including JSON fields

#### Scenario: Transaction rollback
- Given: an initialized real database with existing data
- When: a transaction raises an exception mid-operation
- Then: all changes within that transaction are rolled back

#### Scenario: Foreign key cascade
- Given: a recording with associated transcripts and logs
- When: the recording is deleted
- Then: associated transcripts and logs are cascade-deleted per FK constraints

### Requirement: Provider Contract Tests
**SHALL** test the openai_compatible.py provider against its ABC contract, verifying conformance, error wrapping, and parameter forwarding.

#### Scenario: ABC conformance
- Given: the OpenAICompatibleProvider class
- When: it is instantiated
- Then: it implements all abstract methods defined in the TranscriptionProvider ABC

#### Scenario: Error wrapping
- Given: a provider instance with a mocked OpenAI client that raises an API error
- When: transcribe() is called
- Then: the error is wrapped in the appropriate domain exception type

#### Scenario: Live-mode contract test behind WHISPER_DICTATE_LIVE_CONTRACT
- Given: a live provider contract test in tests/contract/
- When: the suite runs without `WHISPER_DICTATE_LIVE_CONTRACT` set (the default)
- Then: the live test is skipped
- When: `WHISPER_DICTATE_LIVE_CONTRACT` is set and a real provider API key is configured
- Then: the live test synthesizes a minimal WAV, performs a real transcription through the provider seam, and asserts a TranscriptionResult is returned

### Requirement: Audio Storage Filesystem Tests
**SHALL** test audio_storage.py with real filesystem operations in temporary directories.

#### Scenario: Save and retrieve audio file
- Given: a real temporary audio storage directory
- When: an audio file is saved and then retrieved
- Then: the file exists at the expected path and its contents match

#### Scenario: Cleanup old recordings
- Given: a storage directory with recordings of varying ages
- When: cleanup is called with a retention threshold
- Then: only recordings older than the threshold are deleted

### Requirement: Database Logging Tests
**SHALL** test db_logging.py DatabaseLogHandler with a real database and temporary log files.

#### Scenario: Log handler emits to database
- Given: a DatabaseLogHandler connected to a real database
- When: a log record is emitted
- Then: the record is persisted in the logs table with correct level, message, and timestamp

#### Scenario: Dual logging setup
- Given: a temporary log file path and real database
- When: setup_dual_logging() is called
- Then: both file and database handlers are attached to the root logger

### Requirement: Migration Tests
**SHALL** test migration.py detect, run, rollback, and verify operations using module-constant patching for legacy paths.

#### Scenario: Detect legacy data
- Given: a temporary directory with legacy JSON files
- When: migration detect is called with patched LEGACY_* constants
- Then: legacy recordings and transcripts are correctly identified

#### Scenario: Migration rollback
- Given: a completed migration
- When: rollback is called
- Then: the database is restored from backup and legacy files are restored

### Requirement: E2E Dictation Pipeline Test
**SHALL** test the full dictation pipeline with real SQLite and audio storage, mocking only audio capture, API calls, and clipboard.

#### Scenario: Full dictation cycle
- Given: a real SQLite database and audio storage in temp directories
- When: a dictation cycle runs with mocked audio input and API response
- Then: the recording, transcript, and log are persisted, and clipboard receives the transcription text
