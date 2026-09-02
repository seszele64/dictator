# whisper-dictate — Process Quality & Structural Refactoring Roadmap

**Repo:** `whisper-dictate` — a Python 3.11+ CLI dictation tool (~6.9k LOC, 16 modules; `uv` + hatchling packaging; OpenSpec-driven development).
**Current state:** `v0.1.0`. Test discipline is strong (~600 test functions, 32 test files) and the feature work is largely done, but structural debt remains in the god modules (1,148-line `database.py`, 1,004-line `cli.py`, 861-line `audio_storage.py`) and in the stale ADRs (P12).

**What this roadmap covers — and how it merges two deliverables:**

1. **Process / quality roadmap** — 20 prioritized items (P1–P20) across three quality tiers (A → B → C), a 2-week execution plan, and 5 owner decisions (plus a telemetry decision).
2. **Structural / OOP refactoring plan** — target architecture (composition root, constructor DI, no singletons, no dead code), a 16-item dead-code purge, and 6 refactoring phases (S0–S5 + S6 release freeze) with per-phase verification gates.

These two documents are deliberately **merged** into a single document: one timeline (structural phases are placed *inside* the day-by-day plan), one priority list (P-items and S-phases in a single master list), and one decision section. There is no separate "process plan" and "structure plan" — there is only this plan.

Long story short: **the two-week plan takes the repo from "works for me" to a polished, releasable v0.1.x — without a big-bang rewrite.** Every structural change is characterized by tests first (S0), landed behind verification gates, and frozen before release.

---

## How to use this document

- **Track progress** with the status table in [§1](#1-current-state--executive-summary) (phases and tiers) and the *Done* column in the [master work list](#5-prioritized-work-items--merged-master-list). Each item belongs to exactly one of the three tiers; tiers are completed in order **A → B → C** (Tier C items may be explicitly deferred, but may not jump ahead of A/B).
- **Read order for newcomers:** §1 (state) → §2 (tiers) → §7 (the 2-week plan). §3–§5 are the structural deep-dive you consult when a phase references it; §10 decisions gate several items (D1 gates P13, D3 gates P7, D4 gates P10/P9, D5 gates P14/P15).
- **Conventions:** `P#` = process/quality item; `S#` = structural refactoring phase; `D#` = owner decision (human gates, see §10). Impact: H/M/L. Effort: S/M/L (ranges like `M-L` mean "M to L"). File references use current `file:line` locations; structural splits may change them (that's the point).
- **Owner actions:** (a) tick items off the tracking tables as gates pass; (b) all six §10 decisions were locked in writing on 2026-09-02 — none outstanding.

---

## 1. Current state & executive summary

### 1.1 Where the repo is today

**What is good (keep it that way):**

- `v0.1.0` from `pyproject.toml`; `uv` + hatchling packaging; `uv.lock` committed.
- ~600 test functions across `tests/` (unit + integration), with singleton-reset and notification-state fixtures (`conftest.py:130-161`).
- OpenSpec workflow in place with un-archived changes `fix-provider-crash` and `fix-storage-safety` (`openspec/changes/`) and synced specs under `openspec/specs/`.

**What is wrong (remaining debt — the landed items are pruned from this list):**

- **God modules:** `database.py` (1,148L), `cli.py` (1,004L), `audio_storage.py` (861L) — the S3 splits.
- **pydub dependency** (audioop removed in 3.13 → the 3.13 classifier is currently false; the test matrix can't include 3.13 while it remains).

### 1.2 Priority & status tracking (tick off as you go)

| ☐ | Phase / tier | Where | Status |
|---|---|---|---|
| ☐ | **Tier A — Polished production tool** | §2 | ☐ |
| ☐ | **Tier B — Professional hygiene** | §2 | ☐ |
| ☐ | **Tier C — Engineering rigor at scale** | §2, §9 | ☐ |
| ✅ | **S4 — Toggle merge** (unblocked — S2 done) | §7 | ✅ done (Day 3) |
| ✅ | **P7 — mypy strict core** (Day 4) | §7 | ✅ done (Day 4) |
| ☐ | **S3 — God-module splits** (Week 2, Day 5–8) | §7 | ☐ |
| ☐ | **S5 — Notifier wiring** (Day 8) | §7 | ☐ |
| ☐ | **S6 — Release freeze + v0.1.0** (Day 9–10) | §7, §12 | ☐ |

---

## 2. Quality tiers & goals

Ordering rule: **A → B → C**. Complete an entire tier before making progress on the next — they build on each other (B's CI runs A's checks; C's engineering assumes B's hygiene).

### Tier A — Polished production tool
*A stranger can install it, use it via i3, and get an actionable error.*

- **P13** Release pipeline + LICENSE + CHANGELOG | **P6** Exception audit + traceback logging | **P10** pydub removal | **P9** pip-audit

### Tier B — Professional hygiene
*The repo behaves like a maintained open-source project.*

- **P9** CI matrix 3.11/3.12/3.13 | **P7** mypy strict incremental | **P12** ADR fixup + new ADRs | **P8** pre-commit + ruff format | **P11** contracts resolution

### Tier C — Engineering rigor at scale
*Only after A and B. Items may be deferred by design.*

- **P16** Property tests on safety-critical modules | **P17** Fuzz/security review | **P18** Benchmarks | **P14** Local whisper.cpp provider (second ABC instance) | **P15** Plugin entry points (**deferred to a 3rd provider**) | **P19** Local metrics (privacy default) | **P20** i18n/multi-language/a11y/packaging eval

---

## 3. Structural diagnosis

### 3.1 God modules & OOP debt (with file:line evidence)

| Module | LOC | Symptom | Key evidence |
|---|---|---|---|
| `database.py` | 1,148 | God class + module singleton + facade mixing schema, CRUD, migrations, logging, orphan logic | `_database` global at `:1101`; getter/closers at `:1137-1148`; lazy audio import at `:593-597` (cycle) |
| `audio_storage.py` | 861 | Storage mixes path logic, I/O, orphan scan, placeholder | `_audio_storage` global `:689` + getter `:692-706`; `get_recording_path` placeholder `:249-260`; orphan scan `:729` (DEFAULT-config bug) + re-scan `:829` + per-invocation scan `:864` & `:895-897` |
| `cli.py` | 1,004 | Flat command monolith + setup_logging owns sole-canonical logging | logging `:17-106` (duped in `db_logging.py:101-164` + `toggle.py:56-102` — the sole remaining dup; S3 absorbs into `util/logging_setup.py`); literal paths `:34`, `:208`; `--dry-run` `:822-827` not honored, inverted `:860` |
| `notifications.py` | 650 | `PersistentNotification` mutable class state, zero prod callers | class `:323-635` (313L) + helpers `:572-650` + global `:569` |
| `dunst_monitor.py` | 206 | Wraps a 30-L helper in a class + getter | `DunstMonitor :24`, `get_dunst_monitor :180` |
| `toggle.py` (package) | 416 | Third logging copy remains (S3 absorbs into `util/logging_setup.py`); transcription half delegated | raw SQL gone (S4: claim/duration via named `Database` methods); transcribe delegates to `DictationService.transcribe_existing`; logging copy `:56-102` |
| `cli_helpers.py` | 45 | `with_database` decorator builds DB from global, asymmetric close | `:9-45`; `close()` vs `close_database()` |
| `dictation.py` | 436 | Core service is fine — keep near-verbatim as house template | dictation loop `:140-354`; no notifier wiring (P6), no named logger |
| `config.py` | 350 | Side-effect import + unused field | `load_dotenv()` at `:10`; `log_level` at `:264` (zero prod readers) |
| `migration.py` | 510 | Path literals | state/pid/audio + backup dirs at `:28-33` |
| `db_logging.py` | 164 | Duplicate logging | `setup_dual_logging :101-164` (zero callers) |
| `audio_converter.py` | 180 | Test-only converters | `convert_and_keep_wav` / `convert_and_delete_wav` `:154-180` |

### 3.2 Dead / stale code — purge list fully landed

All 16 items of the original purge list have landed: items 1–9, 11, 13–16 via S1/S2/P3, item 10 (root `toggle_dictate.py` + its tests) via S4, and item 12 (ADR 0001/0002 "Proposed" with stale references) via P12 — both on Day 3. No rows remain.

---

## 4. Target architecture

### 4.1 Principles (8)

1. **Composition root only in the CLI entry.** One place builds the whole object graph; everything else receives dependencies.
2. **Constructor DI everywhere — no singletons.** `DictationService` is the house template (constructor-injected, no hidden globals).
3. **One class = one concern.** A 1,148-line database class is the anti-pattern this roadmap removes.
4. **No dead code in the production tree.** Every production symbol has a caller or it is deleted (§3.2).
5. **Interfaces only at real boundaries.** `Notifier` protocol + `TranscriptionProvider` ABC are justified (two implementations each exist or will). No interfaces for `AudioStorage` / `HistoryRepository` / click — that's ceremony, not architecture.
6. **Layers depend downward, acyclic:** `cli → services → providers | audio | storage | notifications | clipboard → config | util`; **persistence never imports audio** (kills the `database.py:593-597` cycle).
7. **Explicit over magical.** Every `Database` / `AudioStorage` is visibly constructed with config at the composition root; `ctx.obj` carries a tiny context object, not hidden globals.
8. **Proportionate to a single-user CLI.** No framework, no bus, no micro-services — the day-one target is a well-factored 15-module CLI, not a platform.

### 4.2 Target package layout

```text
src/whisper_dictate/           # NOTE: current tree is flat whisper_dictate/ at root — src/ is the intended package location (decided in S3)
├── __init__.py                # __version__ (P1)
├── __main__.py
├── app.py                    # COMPOSITION ROOT: load_dotenv → Config → build service graph → dispatch
├── config.py                  # pydantic Config; DROP log_level :264; DROP load_dotenv side effect :10
├── util/
│   ├── paths.py              # AudioPathResolver — pure path logic hoisted OUT of audio_storage (BREAKS THE CYCLE)
│   └── logging_setup.py       # the ONE canonical setup_logging (FROM cli.py:17-106; absorbs db_logging dup + toggle copy)
├── cli/
│   ├── __init__.py            # click group assembly, 8→6 command groups
│   ├── options.py             # shared click options (--config, --db-path, --verbose, --dry-run)
│   ├── invoke.py               # with_database rewritten: builds Database from ctx config, closes in finally (FROM cli_helpers.py:9-45, DELETES cli_helpers.py)
│   └── commands/
│       ├── dictate.py         # dictate/ive
│       ├── history.py          # history
│       ├── audio.py           # audio/cleanup/convert
│       ├── config_cmd.py       # config print/set
│       ├── migrate.py          # migrate
│       └── toggle.py          # NEW — absorbs root toggle_dictate.py (P5)
├── services/
│   ├── dictation.py           # DictationService KEPT (dictation.py:140-354; + optional notifier, + named logger)
│   └── toggle.py              # ToggleService NEW — WM/hotkey/state orchestration (FROM toggle_dictate.py 455L → ~120L)
├── providers/
│   ├── base.py               # TranscriptionProvider ABC (transcription.py)
│   ├── openai.py              # OpenAICompatibleProvider (unchanged)
│   └── factory.py             # provider factory (transcription.py:127-147 verbatim)
├── audio/
│   ├── recorder.py            # existing recorder module
│   └── converter.py            # audio_converter.py MINUS convert_and_keep_wav / convert_and_delete_wav :154-180
├── storage/
│   ├── connection.py          # ConnectionManager — sqlite conn + RLock + transaction helpers (NEW)
│   ├── database.py             # Database — schema init + migration dispatch + thin facade over ConnectionManager (shrunk from 1,148L)
│   ├── migrations.py           # MigrationService
│   ├── history_repo.py         # HistoryRepository — CRUD out of database.py (~half its LOC)
│   ├── log_repo.py            # LogRepository — DB log-table CRUD
│   ├── audio_storage.py       # AudioStorage — real I/O only: atomic session files, finalize, delete (MINUS paths, MINUS orphan scan, MINUS placeholder)
│   └── orphan_scan.py          # OrphanScanner — explicit-config scan (FROM audio_storage.py:729,829; kills double-scan)
├── notifications/
│   ├── notifier.py             # Notifier Protocol + DunstNotifier (dunstify wrapper ~40L) (REPLACES PersistentNotification 313L)
│   └── dunst.py               # ensure_dunst_running (FROM dunst_monitor.py ~30L; DunstMonitor class DELETED)
└── clipboard.py               # xclip wrapper (unchanged)
Root deletions: toggle_dictate.py (after P5 cut-over), tests/contract/ (empty), .opencode/ + .specify/ + .memories/ (git rm). specs/002 → deprecated via P3.
```

### 4.3 Before → after

| Module | Before | After |
|---|---|---|
| `database.py` | 1,148L god class + `_database` singleton | `storage/connection.py` (ConnectionManager) + `storage/database.py` (thin facade) + `storage/migrations.py` + `storage/history_repo.py` + `storage/log_repo.py` |
| `audio_storage.py` | 861L: paths + I/O + orphan scan + placeholder | `util/paths.py` + `storage/audio_storage.py` (I/O only) + `storage/orphan_scan.py` |
| `cli.py` | 1,004L flat monolith + logging `:17-106` | `cli/` package (assembly ~40L, options, invoke, commands/*) — `util/logging_setup.py` owns logging |
| `notifications.py` | 650L (313L class w/ zero callers) | `notifications/notifier.py` (~40L) + `notifications/dunst.py` |
| `dunst_monitor.py` | 206L (class + getter) | ~30L `ensure_dunst_running` in `notifications/dunst.py` |
| `toggle_dictate.py` (root) | 455L w/ raw SQL + logging copy | `services/toggle.py` (~120L) + `cli/commands/toggle.py` |
| `cli_helpers.py` | 45L | replaced by `cli/invoke.py` (deleted) |
| `dictation.py` / `transcription.py` | 436L / 148L | kept near-verbatim; moved to `services/` + `providers/` |

### 4.4 Dependency graph (acyclic target)

```text
app.py / __main__.py
  └─ cli/*
       └─ services/*
            ├─ providers/* (base, openai, factory)
            ├─ audio/* (recorder, converter)
            ├─ storage/* (connection, database, migrations, history_repo, log_repo, audio_storage, orphan_scan)
            │     └─ config, util/paths     ✗ NEVER audio/*
            ├─ notifications/* (notifier, dunst)
            └─ clipboard
util/, config/ are leaves.
database.py:593-597 → audio_storage edge removed by: path hoist to util/paths.py + orphan logic to storage/orphan_scan.py.
```

### 4.5 Class redesign (how the gods are split)

- **Database (1,148L) →** `ConnectionManager` (owns the sqlite conn + `RLock` instance field, `transaction()` context manager) + `Database` (schema init + migration dispatch + thin facade; **zero CRUD**) + `MigrationService` + `HistoryRepository` + `LogRepository`. Repositories take the *Database object* (not the raw conn) so lock/transaction semantics live in one place. Per-command per-invocation instance created at the composition root — `build_database(config)`; `with_database` constructs a fresh instance in the callback and closes in `finally`. Kills `_database` global (`database.py:1101`) + getter/closers; kills asymmetric `close()` vs `close_database()` (`:1137-1148`).
- **AudioStorage (861L) →** `util/paths.AudioPathResolver` (pure functions: session path, final path, dirs from `AudioConfig`; no I/O; chokepoint; placeholder `get_recording_path :249-260` **DELETED, not moved**) + `storage/audio_storage.AudioStorage` (I/O only; constructor `AudioStorage(config: AudioConfig, paths: AudioPathResolver)`; `_audio_storage` global `:689` + `get_audio_storage :692-706` DELETED) + `storage/orphan_scan.OrphanScanner` (`scan(paths, db)` with explicit config/resolver params; fixes DEFAULT-config bug `:729`; CLI scans once per invocation for both display `:864` and delete `:895-897`; internal re-scan `audio_storage.py:829` removed).
- **cli.py (1,004L) →** `cli/` package (group assembly ~40L; `options.py` shared options incl `--dry-run` now actually read; `commands/*.py` one module per concern, thin parse→call-service; `invoke.py` replaces `cli_helpers.py` with a new `with_database` decorator reading `ctx.obj.config`, constructing `Database`, closing in `finally`; `ctx.obj` = `CliContext(config, factories)` dataclass — **factories, not instances**; composition root in `app.py` above `cli/`; flat `cli.py` deleted).
- **notifications.py (650L) →** delete `PersistentNotification :323-635` (313L), 4 helpers `:572-650`, global `_recording_notification :569`; keep the dunstify invocation as **Notifier Protocol + `DunstNotifier`** (subprocess.call dunstify ~40L, injectable command runner for tests); wire into `DictationService` as an **OPTIONAL constructor param** `notifier: Notifier | None = None`; CLI builds one when `config.notifications.enabled` (default False); `click.echo` stays primary UX; **zero behavior change by default**.
- **dunst_monitor.py (200L → ~30L):** delete `DunstMonitor :24` + `get_dunst_monitor :180`; move `ensure_dunst_running` into `notifications/dunst.py`; imported by `ToggleService` and the `DictationService` notify path.
- **toggle_dictate.py (455L root):** `services/toggle.ToggleService` keeps WM/hotkey orchestration, recording on/off state, session lifecycle; record→transcribe→clipboard step delegates the transcribe→clipboard→DB half to `DictationService.transcribe_existing()` (added S4; toggle keeps arecord/PID/state orchestration); third logging copy `:42-83` deleted in favor of `util/logging_setup.py`; `cli/commands/toggle.py` entry; `setup_i3.sh:4` + `generate_run_script.sh:19` point at the new console script; `conftest.py:23` sys.path hack removed; `tests/integration/test_toggle_dictate.py` rewritten against the package API; the typo (and the file) dies with the old name.
- **DictationService / OpenAICompatibleProvider:** kept near-verbatim (house template); deltas: optional `notifier` param, `logging.getLogger(__name__)` (P6), module moves `services/dictation.py` + `providers/openai.py` pure moves; provider contract tests stay authoritative (P11).

### 4.6 What we are NOT doing

- DI containers / IoC
- DDD / CQRS / event sourcing / bus
- Unit-of-Work / generic `Repository[T]`
- Hexagonal ceremony (ports & adapters everywhere)
- Plugin framework (P15 — deferred until a 3rd provider is actually wanted)
- Abstract storage/DB interfaces until a 2nd implementation exists
- Click command wrappers (subclassed `click.Command` ceremony)

**Deliberately NOT a rewrite:** every split below is a mechanical move with behavior-preserving tests already in place (S0) — not a redesign of functionality.

---

## 5. Prioritized work items — merged master list

One list, process and structural together, ordered by execution sequence within the 2-week plan (see §7). *Impact*: H/M/L. *Effort*: S/M/L. *Done* column is for the owner.

| # | Done | ID | Type | Item (short) | Impact | Effort | Deps | Slot |
|---|---|---|---|---|---|---|---|---|
| 1 | ✅ | S4 | Structural | Toggle merge (P5 cut-over): `ToggleService` + `cli/commands/toggle.py`; delegation to `DictationService`; entry-point switch `setup_i3.sh:4` + `generate_run_script.sh:19`; delete root script + old tests; `conftest.py:23` removed (H, M-L) — **Done (Day 3)**: cut-over, entry-point switch, shim deleted, raw SQL out, transcribe delegation; `ToggleService` + `cli/commands/toggle.py` land with S3's layout move | H | M-L | S1+S2+P5 (done) | unblocked — lands now that S2 is done |
| 2 | ✅ | P12 | Process | ADR finalization: 0001 rewritten to what exists + Accepted; 0002 → Superseded by ADR 0003; new ADRs: 0003 Composition root (supersedes 0002), 0004 Centralized config, 0005 Provider ABC+factory; future 0006 pydub (P10), 0007 distribution (P13/D1), 0008 local provider (P14) (M, S) — **Done (Day 3)** | M | S | P2 (done), P10-adjacent | Day 3 |
| 3 | ✅ | P7 | Process | Typing gate core modules: mypy strict = true (py3.11), files = `whisper_dictate`; per-module overrides opt-out `cli.py` + `dunst_monitor.py` initially; `warn_unused_ignores`; CI job; ratchet policy (never loosens) — **Done (Day 4)**: strict on all 21 modules, 0 errors; `cli.py` sole explicit-flag lax override (D3; bodies still checked); `dunst_monitor.py` needed no override (strict-clean at introduction); CI job deferred to P9 (Day 7 — includes the mypy job; no CI existed at Day 4); 2 coded ignores (db_logging assignment, openai language wire-payload) | H | M | S2 (done) | Day 4 |
| 4 | ☐ | P8 | Process | pre-commit + ruff format (`.pre-commit-config.yaml` ruff lint + format + EOF/whitespace/yaml/toml/merge-conflict checks; decide ruff format repo-wide one commit; `.editorconfig`; optional dependabot) | M | S | — | Day 5 |
| 5 | ☐ | P11 | Process | Resolve `tests/contract/` honestly (Option A recommended: move provider-contract tests into `tests/contract/test_openai_compatible.py`? — see §3.2/8 — actually: tests live in `tests/unit/test_provider_contract.py`; update spec 008; add contract marker; optional live-mode `@mark.contract-live` behind `WHISPER_DICTATE_LIVE_CONTRACT` skip-by-default; Option B: delete dir + amend spec) | M | S | — | Day 5 |
| 6 | ☐ | S3 | Structural | God-module splits: Database → ConnectionManager/Repos/Migrations; `cli.py` → `cli/` package; `audio_storage` → `util/paths` + `storage/audio_storage` + `orphan_scan` | H | L | S2 (done) | Week 2, Day 5–8 (after mypy locked) |
| 7 | ☐ | P10 | Process | Remove pydub (golden behavior tests first — sample rate, frame counts, duration, silence-trim boundaries; replace w/ soundfile + ffmpeg subprocess where needed; remove dep; prove 3.13 import-clean; README/AGENTS tech line) | H | M | golden tests first (S0 done / P16) | Day 6 |
| 8 | ☐ | P9 | Process | CI matrix 3.11/3.12/3.13 (astral-sh/setup-uv@v8+ enable-cache; `uv sync --frozen --extra dev`; pytest on matrix without `--cov`; separate coverage job on 3.12 w/ `check_coverage.py` + artefact; lint job ruff check + format check + mypy job; pip-audit step; drop pip-based lint) | H | M | P7, P10 (for 3.13) | Day 7 |
| 9 | ☐ | P6 | Process | Exception audit + traceback logging (rotating file handler at `{state_dir}/logs/whisper-dictate.log`, XDG-state; `-v/--verbose` → DEBUG; categorize ~49 excepts; top-level = notify + `logger.exception()`; fault-injection tests) | H | M | — | Day 8 |
| 10 | ☐ | S5 | Structural | Notifier wiring: optional `Notifier` into `DictationService`; dunst smoke tests default off | M | S | S1 (done) + S3 | Day 8 |
| 11 | ☐ | P13 | Process | Release pipeline: LICENSE MIT (owner = D1); CHANGELOG (Keep-a-Changelog backfill + Unreleased); tag==version CI assert; `release.yml` on push tags v* → `uv build` + `uvx twine check` + `uv publish --trusted-publishing always (PyPI OIDC); env: pypi + fork guard; optional test.pypi dry-run; README install split (pipx / uv tool vs from-source) | H | M-L | P1 (done), P9, D1 (locked) | Day 9 |
| 12 | ☐ | S6 | Structural | Release freeze — no structural work; only P1 versioning + P13 pipeline | H | S | S3–S5 (S0–S2, P1 done) | Day 9–10 |
| 13 | ☐ | P16 | Process | Hypothesis property tests (seeds on Day 10; full suite in Tier C): audio_storage containment + roundtrip invariants; database concurrent append/read ordering + CRUD invariants; migration v1→v2 idempotency + backup non-destructive; config env-var strategies parse to valid models or clean errors | M-H | M-L | S0 (done) | Day 10 seed → Tier C |
| 14 | ☐ | P17 | Process | Fuzz/security review (quick subprocess/secret audit on Day 10 → `docs/security.md`; full corpus tests in Tier C): subprocess audit: arg-vectors no `shell=True`, timeouts, env scrubbed of secrets — provider key must NOT reach child env; malformed-input corpus (truncated wav, provider JSON wrong types/huge strings); pip-audit in CI; `docs/security.md` table of call sites | M | M-L | P6, P16 | Day 10 quick → Tier C |
| 15 | ☐ | P14 | Process | Local whisper.cpp provider — **normalized**: `providers/whisper_cpp.py` subprocess `whisper-cli` or `pywhispercpp`; model storage XDG data; download documented, not bundled; contract tests via P11 live-mode; `provider = "whisper-cpp"` in config + README; offline + privacy | M-H | L | P7, P11, D5 | Buffer (see §7) — only if scope fits; otherwise Tier C |
| 16 | ☐ | P15 | Process | Plugin discovery via `importlib.metadata` entry-points — **DEFERRED BY DESIGN** until a 3rd provider is actually wanted | M | L | P14 | Deferred |
| 17 | ☐ | P18 | Process | Performance baselines (`scripts/bench.py`: cold-start `whisper-dictate --help` wall time ×N, record-path latency mock device, full roundtrip mock provider; `--durations=10` in pytest; `docs/perf.md` baseline committed) | M | M | — | Tier C |
| 18 | ☐ | P19 | Process | Local metrics / stats (`whisper-dictate stats` subcommand: per-day count, avg/p95 latency per provider, error counts from existing SQLite; NO network telemetry ever; opt-in needs ADR + env default off) | L-M | M | P1 (done) | Tier C |
| 19 | ☐ | P20 | Process | i18n / multi-language UX / a11y / packaging eval (gettext pass on `notifications.py` + `cli.py` strings, stdlib gettext, `.pot` extraction; language/translate provider params wired through CLI + README; screen-reader flow doc; `spd-say` optional hook; packaging eval: CLI + system deps → flatpak poor fit → documented `uv tool install` as supported path) | M | L | P13 | Tier C |

---

## 6. Short-term quick wins — landed

Every quick win in this section (S0 characterization, the S1 dead-code purge incl. `--dry-run`, P1 versioning, README truth restoration) is deployed and pruned from this roadmap. Section numbering is retained so cross-references stay stable; the remaining plan continues in §7.

---

## 7. Merged 2-week execution plan

Structural phases (S0–S6) are interleaved with the process items (P1–P20) — **one timeline, not two**. Day = working day; buffer absorbs overruns.

### Critical path & coupling

- **Structural spine:** S0 → S1 → S2 are landed (composition root + per-command Database via `with_database` are in place); **S3** is the remaining split.
- **Toggle spine:** S4 is the remaining cut-over — P5's package toggle + console script exist, and the root shim plus `conftest.py:23` sys.path hack await deletion.
- **Remaining coupling:** land **P7 (mypy, Day 4) before the big S3 splits (Day 5–8)** so mypy does not type-check code that is about to move; S4 is unblocked (S2 done) and independent.

### Release-window rules (Day 9–10)

- No module splits / renames, no toggle cut-over, no test deletions, no dep changes inside the Day 9–10 freeze.
- All structural commits land **before** the freeze.
- **Never** delete `toggle_dictate.py` before the scripts point at the new entry.
- **Never** delete a test before its replacement is green.

### Week 1 — cut-over, ADRs, typing (remaining)

| Day | Focus | Work | Gate |
|---|---|---|---|
| **3** | Toggle cut-over + ADR pass | ✅ **done** — **S4** toggle merge (root shim deletion + entry-point switch; unblocked — S2 done); **P12** ADR fixes + 0003/0004/0005 | Gate passed: i3/run-script entries verified by simulation; `docs/adr` references only existing files; full suite + ruff + coverage + snapshot green |
| **4** | Type-checking foundation | ✅ **done** — **P7** mypy strict core (`cli.py` deferred explicit override) | Gate passed: `uv run mypy` clean (mypy 2.3.1, py3.11); ratchet enforced by pyproject (strict default, opt-out only via explicit override, never added) |
| **5** | Hygiene | **P8** pre-commit + ruff format decision/landing; **P11** contracts move; **S3** starts (god-module splits can start once mypy locked) | End-Week-1 gate: full local suite + mypy + ruff green; one logic change per day |

### Week 2 — supply chain, CI, observability, release

| Day | Focus | Work | Gate |
|---|---|---|---|
| **6** | Supply chain | **P10** pydub golden tests → soundfile/ffmpeg → 3.13 proof | pydub import-free grep; golden tests pass; suite green 3.13 |
| **7** | CI that means what it says | **P9** matrix + frozen + cache + mypy job + pip-audit | all matrix jobs green on PR branch; deliberate `uv.lock` desync fails loudly; coverage artefact uploads |
| **8** | Observability | **P6** exception audit + file logging + `-v`; **S5** notifier wiring; **S3** completion | injected failure produces notification AND log traceback; grep `except Exception` count documented |
| **9** | Release machinery | **P13** LICENSE, CHANGELOG backfill, `release.yml`, README install split (**release freeze starts**: no structural work) | `uv build` + `twine check` clean; test.pypi dry-run succeeds; fork-push dry-run does NOT publish |
| **10** | Verification + first release | **S6** freeze; **P16** seed property suites; **P17** quick subprocess/secret audit → `docs/security.md`; README/AGENTS final pass; cut v0.1.0 | fresh-clone checklist end-to-end; release tag on PyPI; GitHub Release notes |

**Buffer days 11–14:** absorb pydub/my py overruns. If clean → scope **P14** properly, but **do NOT start it in the same two weeks if it risks the release** (P14 lands in Tier C or a dedicated window, never against the freeze).

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| pydub removal changes audio behavior silently | Golden behavior tests first (P10), tolerance comparisons, full suite on 3.13 |
| CI matrix adds 3× runtime | Coverage on one job only; uv cache; `--frozen` catches drift |
| Release ceremony swallows the 2-week budget | P13 is 1 day with uv + trusted publishing; test.pypi dry-run only |
| AI-assisted changes re-drift specs | P3 single-sources specs; AGENTS hook stays current |

---

## 9. Longer-term / strategic (Tier C & deferred)

Everything here is explicitly out of the 2-week window (except Day-10 *seeds* of P16/P17). Do not start Tier C work before Tiers A and B are done.

- **P16 — Hypothesis property tests (full):** audio_storage containment + roundtrip invariants; database concurrent append/read ordering + CRUD invariants; migration v1→v2 idempotency + backup non-destructive; config env-var strategies parse to valid models or clean errors. Add `hypothesis` to dev deps.
- **P17 — Fuzz / security review (full):** subprocess audit (arg-vectors, no `shell=True`, timeouts, env scrubbed — provider key must never reach child env); malformed-input corpus (truncated wav, provider JSON wrong types / huge strings); pip-audit in CI; `docs/security.md` call-site table (Day-10 quick pass seeds this).
- **P18 — Performance baselines:** `scripts/bench.py` (cold-start `--help` wall time ×N, record-path latency w/ mock device, full roundtrip w/ mock provider); `--durations=10` in pytest; `docs/perf.md` committed.
- **P19 — Local metrics / stats:** `whisper-dictate stats` subcommand — per-day count, avg/p95 latency per provider, error counts from the existing SQLite; **NO network telemetry, ever**; opt-in needs an ADR + env default off.
- **P20 — i18n / a11y / packaging eval** gettext pass on `notifications.py` + `cli.py`; stdlib gettext, `.pot` extraction; language/translate provider params through CLI + README; screen-reader flow doc; optional `spd-say` hook; packaging: CLI + system deps → flatpak is a poor fit → document `uv tool install` as the supported path.
- **P14 — Local whisper.cpp provider:** the one capability with real new value (offline, privacy, no API cost). Only if D5 says yes; only when P7 + P11 are in place; contract tests pay for themselves. If never wanted → skip P14 entirely, P15 stays closed, and Tier C shrinks by three rows.
- **P15 — plugin entry points:** **deferred by design** until a 3rd provider is actually wanted; `importlib.metadata` entry-points. The ABC + factory is already the right seam; a plugin framework now would be gold-plating.

**Strategic priors:** the ABC + factory seam (P14) and the local-SQLite stats (P19) are the two extensions with enduring value; everything else in Tier C is polish or process hardening.

---

## 10. Decisions for the owner

Five decisions plus one bonus — **all six were locked in writing by the owner on 2026-09-02** (D1/D3/D4 ahead of the Day-4 deadline); see the Locked column. Each decision has a recommendation; the "if no" column says what the plan loses.

| ID | Decision | Recommendation | If declined… | Locked (2026-09-02) |
|---|---|---|---|---|
| **D1** | Distribution intent: personal vs public PyPI | **Public-PyPI-ready, low ceremony** — `uv tool install whisper-dictate`. | Drop the P13 publish job; keep LICENSE + CHANGELOG; skip OSS-Fuzz; telemetry becomes moot | ✅ Public-PyPI-ready (low ceremony, `uv tool install`; full P13 publish job + LICENSE + CHANGELOG) |
| **D2** | Stale streaming spec (`specs/002`): implement / delete / re-scope | **Delete from legacy specs now** (ghost weight; never implemented; not in openspec). Fold streaming into the local-provider conversation (P14) if latency is measured as pain. **Never resurrect the stale one.** | Keeping it re-drifts documentation and re-opens an unimplemented feature | ✅ executed via P3 (`ba92531`); never resurrect |
| **D3** | Typing rigor: how far, how fast | **mypy strict on core now**; `cli.py` lax explicit override; fail-new-errors policy. (pyright is a fine alternative — recommend mypy for ecosystem + pre-commit/CI maturity; if the mypy message style is intolerable → pyright strict, same incremental list) | Slower typing rollout; ratchet starts lower | ✅ mypy strict on core now; `cli.py` explicit lax override; fail-new-errors ratchet |
| **D4** | pydub: replace or keep-pinned | **Replace** (soundfile + ffmpeg-only-when-needed). audioop is gone in 3.13 → the 3.13 classifier is currently false, and the P9 matrix depends on this. | Keep-pinned → drop the 3.13 classifier forever + pip-audit flags forever. Either way: golden tests first (P10) kills silent-drift risk | ✅ Replace pydub (soundfile + ffmpeg-only-when-needed); golden behavior tests first (P10) |
| **D5** | Provider ambition: when does `providers/` get real? | **One local provider (whisper-cpp) as the 2nd ABC instance** + NO plugin/entry-point system until a 3rd provider is actually wanted (P15 deferred). ABC + factory is already the right seam; plugins now = gold-plating. | If a local provider is never needed: skip P14, keep P15 closed, Tier C shrinks | ✅ One local provider (whisper-cpp) later as 2nd ABC instance (P14, post-release); P15 plugin system stays closed until a 3rd provider is wanted |
| **B30** | Telemetry posture (bonus) | **Local SQLite stats only, zero network ever.** Revisit only with an explicit ADR + opt-in if a real audience materializes (ties to D1) | Non-local telemetry would require a full ADR + explicit opt-in — default is never | ✅ Local SQLite stats only, zero network telemetry ever |

---

## 11. Verification gates — master checklist

Each phase lands **only when its gate passes.** Additionally, every phase lands with: pytest green, ruff clean, **mypy strict-core green from Day 4 onward** (P7), snapshot diff human-reviewed, and no release-window violations (Day 9–10).

| Phase | Gate (pass = tick) |
|---|---|
| **S3** | ☐ no `src/**/*.py` ≥ 600 lines; ☐ import graph acyclic (`import-linter` in CI as a lint step; forbidden rule: storage → audio); ☐ per-module coverage gates ≥ current (P4 fail_under); ☐ CLI snapshot diffs = empty |
| **S4** | ✅ `whisper-dictate toggle --help` exits 0; ✅ `setup_i3.sh` + `generate_run_script.sh` produce valid entries; ✅ root `toggle_dictate.py` absent; ✅ `conftest.py:23` absent; ✅ toggle integration green; ✅ `grep ".execute("` outside `storage/` → 0. Gate is interpreted pre-S3: `storage/` does not exist yet; it means **no `.execute(` consumers outside the database module** — `database.py` may define and internally use `.execute(` (incl. `update_recording_file_path`/`update_recording_duration`). Precedent: S2's benign-families note. |
| **S5** | ☐ notifications enabled smoke → dunst message; ☐ default → no message; ☐ full suite green |
| **Global** | ☐ pytest green; ☐ ruff clean; ☐ mypy strict-core green (Day 4+); ☐ snapshot diff human-reviewed; ☐ no release-window violations |
| **Fresh-clone checklist** (medium-term gate) | ☐ `uv sync --frozen`; ☐ pre-commit green; ☐ mypy + ruff clean; ☐ full pytest 3.11/3.12/3.13; ☐ pip-audit clean; ☐ `whisper-dictate-toggle` installed; ☐ fault-injection test proves traceback lands in the log |

---

## 12. Definition of done — v0.1.0

The release is done when **all** of the following hold:

- ☐ `whisper-dictate --version` works and all installed console scripts (incl. `whisper-dictate-toggle`) run from a fresh `uv tool install`.
- ☐ CI green on 3.11/3.12/3.13: lint, format, mypy core-strict, full tests, coverage gate, pip-audit.
- ☐ No pydub in the dep tree.
- ☐ Fault injection produces a traceback in `{state_dir}/logs/` **and** a useful dunst notification (P6).
- ☐ `docs/adr` all final status (Accepted or Superseded), no Proposed, referencing only existing files (P12).
- ☐ LICENSE + CHANGELOG + tag-publishing workflow live (P13, D1).
- ☐ Property tests cover path-containment + migration idempotency (P16 seeds).
- ☐ `docs/security.md` lists every subprocess call site (P17 quick audit).

*Then cut `v0.1.0`, write the GitHub Release notes, and — if the buffer was clean and D5 says yes — scope P14 as the first post-release item.*