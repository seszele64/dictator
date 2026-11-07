#!/bin/bash
# Setup i3 global key binding for whisper-dictate

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
I3_CONFIG="$HOME/.config/i3/config"

# Prefer the repo-local venv's console script; fall back to PATH so a
# system-wide install (`uv tool install whisper-dictate`) still works when
# this script runs from a checkout without a .venv.
if [ -x "$REPO_ROOT/.venv/bin/whisper-dictate-toggle" ]; then
    TOGGLE_CMD="$REPO_ROOT/.venv/bin/whisper-dictate-toggle"
else
    TOGGLE_CMD="whisper-dictate-toggle"
fi
# Same resolution strategy for the post-processing command: prefer the
# repo-local console script, fall back to PATH for a system-wide install.
if [ -x "$REPO_ROOT/.venv/bin/whisper-dictate" ]; then
    PROCESS_CMD="$REPO_ROOT/.venv/bin/whisper-dictate process"
else
    PROCESS_CMD="whisper-dictate process"
fi
DICTATE_BINDING="bindsym \$mod+t exec --no-startup-id $TOGGLE_CMD"
PROCESS_BINDING="bindsym \$mod+p exec --no-startup-id $PROCESS_CMD"
DUNST_CONTEXT_BINDING="bindsym Ctrl+Shift+. exec dunstctl context"

# A line is treated as a binding only when its first non-whitespace token is
# `bindsym`; `#` is i3's comment character, so `# bindsym ...` and indented
# comments never match and stay byte-identical.
#   MODP_BINDING_PATTERN  - an active $mod+p / Mod4+p / Super+p binding.
#   PROCESS_ACTIVE_PATTERN - an active binding that runs the process command
#                            (current `whisper-dictate process` or the legacy
#                            `post-process-prompt` shim).
MODP_BINDING_PATTERN='^[[:space:]]*bindsym[[:space:]]+(\$mod|Mod4|Super)\+p([[:space:]]|$)'
PROCESS_ACTIVE_PATTERN='^[[:space:]]*bindsym[[:space:]].*(whisper-dictate[[:space:]]+process|post-process-prompt)'

echo "Setting up i3 global key binding for whisper-dictate..."

# Check if i3 config exists
if [ ! -f "$I3_CONFIG" ]; then
    echo "i3 config not found at $I3_CONFIG"
    exit 1
fi

# Normalize any existing dictation binding to the canonical line below.
# Matches the removed root toggle_dictate.py shim (pre-S4 cut-over) AND any
# whisper-dictate-toggle binding regardless of the mod key, so re-runs are
# idempotent and a legacy Super+Z binding from an older setup_i3.sh is
# migrated to Super+T instead of piling up. Other keybindings (e.g. the
# user's `bindsym $mod+z workspace prev`) do not match and are untouched.
# NOTE: Super+Z is deliberately NOT used for dictation - it silently
# overwrites the user's existing `$mod+z` binding (last binding wins in i3).
sed -i -E "s#^bindsym .*(whisper-dictate-toggle|toggle_dictate\.py).*\$#$DICTATE_BINDING#" "$I3_CONFIG"

# The rewrite above maps every matching line to the same canonical line, so a
# config carrying both the legacy shim and the current binding would end up
# with two identical `$mod+t` lines. Collapse exact duplicates of the
# canonical line down to its first occurrence; unrelated lines (other
# bindings, comments, blank lines) are printed verbatim.
# Write via a temp file and copy back into the original inode so the config's
# existing permissions/ownership are preserved (mktemp avoids name clashes).
I3_TMP="$(mktemp "$I3_CONFIG.XXXXXX")"
awk -v canon="$DICTATE_BINDING" '
    $0 == canon { if (seen++) next }
    { print }
' "$I3_CONFIG" > "$I3_TMP" && cat "$I3_TMP" > "$I3_CONFIG" && rm -f "$I3_TMP"

# Check if dictation binding already exists
if grep -Eq "^bindsym .*whisper-dictate-toggle" "$I3_CONFIG"; then
    echo "Key binding already exists in i3 config for whisper-dictate"
else
    # Add the key binding
    echo "" >> "$I3_CONFIG"
    echo "# Voice dictation toggle - Super+T" >> "$I3_CONFIG"
    echo "$DICTATE_BINDING" >> "$I3_CONFIG"
    echo "Added key binding: Super+T"
fi

# --- Post-processing binding ($mod+p) ---
# Normalize any existing whisper-dictate process binding (the current
# `whisper-dictate process` command or the legacy `post-process-prompt` shim)
# to the canonical line, regardless of the modifier key. Only active lines
# whose first non-whitespace token is `bindsym` match, so `# bindsym ...` and
# indented comments are left byte-identical.
sed -i -E "s#^[[:space:]]*bindsym[[:space:]].*(whisper-dictate[[:space:]]+process|post-process-prompt).*\$#$PROCESS_BINDING#" "$I3_CONFIG"

# Collapse duplicate canonical process lines down to the first occurrence,
# printing unrelated lines verbatim (same approach as the $mod+t pass above).
I3_TMP="$(mktemp "$I3_CONFIG.XXXXXX")"
awk -v canon="$PROCESS_BINDING" '
    $0 == canon { if (seen++) next }
    { print }
' "$I3_CONFIG" > "$I3_TMP" && cat "$I3_TMP" > "$I3_CONFIG" && rm -f "$I3_TMP"

# Append only when no active process binding exists. An unrelated active
# $mod+p / Mod4+p / Super+p binding is never clobbered: i3 resolves duplicate
# keys last-binding-wins, so appending would silently disable the user's
# command. Print the exact line to add manually instead.
if grep -Eq "$PROCESS_ACTIVE_PATTERN" "$I3_CONFIG"; then
    echo "Key binding already exists in i3 config for whisper-dictate process"
elif grep -Eq "$MODP_BINDING_PATTERN" "$I3_CONFIG"; then
    echo "WARNING: an unrelated \$mod+p binding already exists; not overwriting it."
    echo "Add this line manually to install the post-processing binding:"
    echo "    $PROCESS_BINDING"
else
    echo "" >> "$I3_CONFIG"
    echo "# Post-process latest transcript - Meta+P" >> "$I3_CONFIG"
    echo "$PROCESS_BINDING" >> "$I3_CONFIG"
    echo "Added key binding: Meta+P"
fi

# Check if dunstctl context binding already exists (required for notification actions)
if grep -q "dunstctl context" "$I3_CONFIG"; then
    echo "Dunst context keybinding already exists in i3 config"
else
    # Add the dunst context keybinding
    echo "" >> "$I3_CONFIG"
    echo "# Dunst context menu - Required for notification action buttons" >> "$I3_CONFIG"
    echo "$DUNST_CONTEXT_BINDING" >> "$I3_CONFIG"
    echo "Added key binding: Ctrl+Shift+."
fi

# Reload i3
i3-msg reload
echo "i3 configuration reloaded!"
echo "Press Super+T to test voice dictation"
echo "Press Meta+P to post-process the latest transcript with a prompt"
echo "Press Ctrl+Shift+. to access dunst context menu (for notification actions)"
