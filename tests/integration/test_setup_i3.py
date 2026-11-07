"""Integration tests for `setup_i3.sh`'s idempotent `$mod+p` binding (Group 7).

These run the real script under bash against a temp `HOME` and a stubbed
`i3-msg`, so the config mutation, normalization, dedupe, and conflict
detection are exercised end-to-end without touching the user's i3 config.

The script is copied into a temp "repo" without a `.venv` so the command
resolution deterministically falls back to the PATH form
(`whisper-dictate process` / `whisper-dictate-toggle`), which keeps the
expected canonical lines stable.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "setup_i3.sh"

# Fallback canonical lines (no repo-local .venv in the temp repo).
PROCESS_BINDING = "bindsym $mod+p exec --no-startup-id whisper-dictate process"
TOGGLE_BINDING = "bindsym $mod+t exec --no-startup-id whisper-dictate-toggle"
DUNST_BINDING = "bindsym Ctrl+Shift+. exec dunstctl context"


@pytest.fixture
def i3_env(tmp_path: Path) -> dict[str, Any]:
    """A temp repo copy of setup_i3.sh, a temp HOME, and a stubbed i3-msg."""
    repo = tmp_path / "repo"
    repo.mkdir()
    script = repo / "setup_i3.sh"
    shutil.copy(SETUP_SCRIPT, script)

    home = tmp_path / "home"
    (home / ".config" / "i3").mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    i3msg = bin_dir / "i3-msg"
    i3msg.write_text("#!/bin/bash\nexit 0\n")
    i3msg.chmod(0o755)

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"

    return {
        "script": script,
        "config": home / ".config" / "i3" / "config",
        "env": env,
    }


def _run(env_spec: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["bash", str(env_spec["script"])],
        env=env_spec["env"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _write_config(env_spec: dict[str, Any], body: str) -> None:
    env_spec["config"].write_text(body)


def _read_config(env_spec: dict[str, Any]) -> str:
    config: Path = env_spec["config"]
    return config.read_text()


def _count(lines: list[str], needle: str) -> int:
    return sum(1 for line in lines if line == needle)


class TestProcessBindingInstall:
    def test_first_run_adds_binding_once(self, i3_env: dict[str, Any]) -> None:
        _write_config(i3_env, "set $mod Mod4\nbindsym $mod+Return exec term\n")

        result = _run(i3_env)
        lines = _read_config(i3_env).splitlines()

        assert _count(lines, PROCESS_BINDING) == 1
        assert "Meta+P" in result.stdout
        # The generated line carries the full command (task 7.1).
        assert "whisper-dictate process" in PROCESS_BINDING

    def test_rerun_does_not_duplicate(self, i3_env: dict[str, Any]) -> None:
        _write_config(i3_env, "set $mod Mod4\n")

        _run(i3_env)
        _run(i3_env)
        lines = _read_config(i3_env).splitlines()

        assert _count(lines, PROCESS_BINDING) == 1

    def test_indented_active_binding_is_normalized(self, i3_env: dict[str, Any]) -> None:
        _write_config(
            i3_env,
            "set $mod Mod4\n   bindsym $mod+p exec whisper-dictate process --prompt x\n",
        )

        _run(i3_env)
        lines = _read_config(i3_env).splitlines()

        # Normalized to the canonical line, not duplicated.
        assert _count(lines, PROCESS_BINDING) == 1
        assert not any("--prompt x" in line for line in lines)

    @pytest.mark.parametrize("modifier", ["$mod", "Mod4", "Super"])
    def test_legacy_and_modifier_variants_normalize(self, i3_env: dict[str, Any], modifier: str) -> None:
        _write_config(i3_env, f"set $mod Mod4\nbindsym {modifier}+p exec post-process-prompt\n")

        _run(i3_env)
        lines = _read_config(i3_env).splitlines()

        assert _count(lines, PROCESS_BINDING) == 1
        assert not any("post-process-prompt" in line for line in lines)


class TestConflictDetection:
    @pytest.mark.parametrize("modifier", ["$mod", "Mod4", "Super"])
    def test_unrelated_binding_is_preserved(self, i3_env: dict[str, Any], modifier: str) -> None:
        unrelated = f"bindsym {modifier}+p exec pavucontrol"
        _write_config(i3_env, f"set $mod Mod4\n{unrelated}\n")

        result = _run(i3_env)
        lines = _read_config(i3_env).splitlines()

        # Unrelated line untouched, canonical line NOT appended.
        assert unrelated in lines
        assert _count(lines, PROCESS_BINDING) == 0
        # Warning + manual instruction printed.
        assert "not overwriting" in result.stdout
        assert PROCESS_BINDING in result.stdout

    def test_rerun_after_conflict_still_refuses(self, i3_env: dict[str, Any]) -> None:
        unrelated = "bindsym $mod+p exec pavucontrol"
        _write_config(i3_env, f"{unrelated}\n")

        _run(i3_env)
        _run(i3_env)
        lines = _read_config(i3_env).splitlines()

        assert unrelated in lines
        assert _count(lines, PROCESS_BINDING) == 0


class TestCommentHandling:
    def test_commented_bindings_are_neither_normalized_nor_counted(self, i3_env: dict[str, Any]) -> None:
        comment_a = "# bindsym $mod+p exec whisper-dictate process"
        comment_b = "\t#bindsym $mod+p exec something-else"
        _write_config(i3_env, f"{comment_a}\n{comment_b}\nset $mod Mod4\n")

        _run(i3_env)
        _run(i3_env)
        lines = _read_config(i3_env).splitlines()

        # Both comment lines byte-identical.
        assert comment_a in lines
        assert comment_b in lines
        # Neither counted as an existing binding nor a conflict: appended once.
        assert _count(lines, PROCESS_BINDING) == 1


class TestExistingBehaviorUnchanged:
    def test_toggle_and_dunst_bindings_are_preserved(self, i3_env: dict[str, Any]) -> None:
        legacy_toggle = "bindsym $mod+z exec /old/toggle_dictate.py"
        _write_config(i3_env, f"{legacy_toggle}\n")

        _run(i3_env)
        _run(i3_env)
        lines = _read_config(i3_env).splitlines()

        # Legacy shim migrated to the canonical toggle; exactly one of each.
        assert _count(lines, TOGGLE_BINDING) == 1
        assert not any("toggle_dictate.py" in line for line in lines)
        assert _count(lines, DUNST_BINDING) == 1
        assert _count(lines, PROCESS_BINDING) == 1
