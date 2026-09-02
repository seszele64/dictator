# Persistent Notification Specification

## Purpose

This specification defines the persistent notification behavior of the whisper-dictate system during recording sessions. It covers closing the persistent notification when recording stops, graceful handling when the notification daemon (dunstify) is unavailable, and validation when stopping a persistent notification.

> Note: this file was originally synced as a delta (`## MODIFIED Requirements`) from the archived change `fix-notification-persistent-dismiss` and has since been reformatted into the full spec format; the requirements below are unchanged.

## Requirements

### Requirement: Persistent notification closes properly when recording stops
The system SHALL close the persistent notification when recording stops, including checking for dunstify availability before attempting to close.

#### Scenario: Close notification when dunstify is available
- **WHEN** recording stops and dunstify is available on the system
- **THEN** the system executes `dunstify -C <notification_id>` to close the notification and returns success

#### Scenario: Close notification when dunstify is NOT available
- **WHEN** recording stops and dunstify is NOT available on the system
- **THEN** the system logs a warning and returns success without attempting to close (nothing to close)

#### Scenario: Close notification when notification is not active
- **WHEN** close() is called but no notification is currently active
- **THEN** the system returns success without attempting any close operation

---

### Requirement: Graceful handling when notification daemon is unavailable
The system SHALL handle gracefully when the notification daemon (dunstify) is unavailable, both when opening and closing notifications.

#### Scenario: Open notification when dunstify is unavailable
- **WHEN** recording starts and dunstify is NOT available
- **THEN** the system falls back to notify-send or returns None without errors

#### Scenario: Close notification when dunstify becomes unavailable after open
- **WHEN** dunstify was available when notification opened, but becomes unavailable before close
- **THEN** the system logs a warning and returns success (notification may remain but system state is consistent)

---

### Requirement: Proper validation when stopping persistent notification
The system SHALL validate that a notification ID exists before attempting to close, and log a warning if no ID is found.

#### Scenario: Stop notification when no ID is saved
- **WHEN** notify_recording_persistent_stop() is called but no notification ID was saved
- **THEN** the system logs a warning "No notification ID found" and returns False

#### Scenario: Stop notification with corrupted ID file
- **WHEN** notify_recording_persistent_stop() is called but the saved ID file is empty or corrupted
- **THEN** the system logs a warning "Invalid notification ID" and returns False
