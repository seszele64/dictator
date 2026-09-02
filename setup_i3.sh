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
DICTATE_BINDING="bindsym \$mod+z exec --no-startup-id $TOGGLE_CMD"
DUNST_CONTEXT_BINDING="bindsym Ctrl+Shift+. exec dunstctl context"

echo "Setting up i3 global key binding for whisper-dictate..."

# Check if i3 config exists
if [ ! -f "$I3_CONFIG" ]; then
    echo "i3 config not found at $I3_CONFIG"
    exit 1
fi

# Drop stale bindings pointing at the removed root toggle_dictate.py shim
# (deleted in the S4 cut-over). The block below re-adds the binding pointing
# at whisper-dictate-toggle if no new-style binding exists yet.
sed -i "/toggle_dictate\.py/d" "$I3_CONFIG"

# Check if dictation binding already exists
if grep -q "whisper-dictate-toggle" "$I3_CONFIG"; then
    echo "Key binding already exists in i3 config for whisper-dictate"
else
    # Add the key binding
    echo "" >> "$I3_CONFIG"
    echo "# Voice dictation toggle - Super+Z" >> "$I3_CONFIG"
    echo "$DICTATE_BINDING" >> "$I3_CONFIG"
    echo "Added key binding: Super+Z"
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
echo "Press Super+Z to test voice dictation"
echo "Press Ctrl+Shift+. to access dunst context menu (for notification actions)"