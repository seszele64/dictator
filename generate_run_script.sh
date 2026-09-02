#!/bin/bash
# WHY THIS EXISTS: The original run_whisper_dictate.sh has a hardcoded path that breaks
# when the project is moved or cloned to a different location. This script generates
# a new version with the correct current directory path.

# RESPONSIBILITY: Generate a run_whisper_dictate.sh file with the current working directory.
# BOUNDARIES:
# - DOES: Read current directory, create shell script with correct path
# - DOES NOT: Execute the script, modify existing files beyond the target

# Get current directory
CURRENT_DIR=$(pwd)

# Generate the new run script
cat > run_whisper_dictate.sh << EOF
#!/bin/bash
cd "$CURRENT_DIR"
source .venv/bin/activate
exec whisper-dictate-toggle
EOF

# Make it executable
chmod +x run_whisper_dictate.sh

echo "Generated run_whisper_dictate.sh with current directory: $CURRENT_DIR"