## Context

The original design attempted to fix the ID-based notification closing approach by adding availability checks for dunstify. However, during implementation, a fundamental issue was discovered: **notification IDs are inherently unreliable for cross-process notification management**.

The problems with the ID-based approach include:
1. **Race conditions**: The notification ID returned by dunstify may not match the actual internal dunst ID
2. **Cross-process issues**: Saving IDs to files and loading them in different script invocations is fragile
3. **Timing issues**: The notification may have been closed by other means before the stop command runs
4. **ID mismatch**: dunstify returns its own process exit code, not the dunst notification ID

The dunst maintainers recommend using **stack tags** (x-dunst-stack-tag hint) as the proper solution for this use case.

## Goals / Non-Goals

**Goals:**
- Replace ID-based notification tracking with stack tag approach
- Ensure persistent notification is properly replaced when recording stops
- Maintain graceful fallback when dunstify is unavailable
- Eliminate need for ID file persistence between script invocations

**Non-Goals:**
- Support notification systems other than dunst (stack tags are dunst-specific)
- Add new notification capabilities beyond start/stop replacement

## Decisions

### 1. Use dunst stack tags instead of notification IDs
- **Decision**: Replace the ID-based approach with dunst stack tags (x-dunst-stack-tag hint)
- **Rationale**: Stack tags are the recommended approach by dunst maintainers because:
  - Works across script invocations without needing to save/load IDs
  - Notifications with same stack tag automatically replace each other
  - No race conditions or cross-process synchronization issues
  - Simpler implementation - no file I/O for ID persistence

### 2. notify_recording_start() sends persistent notification with stack tag
- **Decision**: Use `-h string:x-dunst-stack-tag:whisper-dictate-recording` with `-t 0` (infinite timeout) and `-u critical`
- **Rationale**:
  - Stack tag ensures this is the "active" recording notification
  - Timeout 0 makes it persistent (stays until replaced)
  - Critical urgency gives it red color and ensures it appears prominently

### 3. notify_recording_stop() replaces persistent notification with brief message
- **Decision**: Use same stack tag with 2-second timeout and normal urgency
- **Rationale**:
  - Same stack tag causes automatic replacement of the persistent notification
  - 2-second timeout allows the user to see "Recording Stopped" before it auto-dismisses
  - Normal urgency is appropriate for a non-urgent informational message

### 4. Added RECORDING_STACK_TAG constant
- **Decision**: Define `RECORDING_STACK_TAG = "whisper-dictate-recording"` as module constant
- **Rationale**:
  - Centralizes the stack tag value for consistency
  - Makes it easy to modify if needed
  - Documents the magic string in code

### 5. Graceful fallback when dunstify unavailable
- **Decision**: Log warning and return False when dunstify is not available
- **Rationale**: Consistent with other notification functions; prevents errors from propagating

## Technical Details

### How Stack Tags Work

Dunst supports a hint called `x-dunst-stack-tag` that groups notifications into a "stack". When a new notification with the same stack tag is sent:
1. The new notification replaces the existing one with the same tag
2. This happens automatically without needing to know the original notification's ID
3. Works across different process invocations - no ID file needed

### Command Examples

**Start recording:**
```bash
dunstify -h string:x-dunst-stack-tag:whisper-dictate-recording -t 0 -u critical "Recording" "Dictation in progress..."
```

**Stop recording:**
```bash
dunstify -h string:x-dunst-stack-tag:whisper-dictate-recording -t 2000 -u normal "Recording Stopped" "Transcription in progress..."
```

## Risks / Trade-offs

- **Risk**: Stack tags only work with dunst, not other notification daemons
  - **Mitigation**: The implementation already checks for dunstify availability; fallback behavior exists

- **Risk**: None significant - stack tags are a well-supported dunst feature recommended by maintainers

- **Trade-off**: Replaced ID file approach (now deprecated but kept for backward compatibility)
  - **Rationale**: Stack tags are more reliable and eliminate the need for file I/O
