"""
Type definitions and event hierarchy for the collaborative terminal system.

This module provides:
- Immutable event classes for event sourcing
- TypedDict structures for session state and data records
- Exception hierarchy for error handling

All types are designed to be copied across system boundaries and
support deterministic event replay for crash recovery.
"""

from typing import TypedDict, Literal
from dataclasses import dataclass


# =============================================================================
# EXCEPTION HIERARCHY
# =============================================================================

class CollabError(Exception):
    """Base exception for all collab system errors."""
    pass


class InvalidSessionStateError(CollabError):
    """Session state violates invariants."""
    pass


class InvalidTaskStateError(CollabError):
    """Task status violates state machine invariants."""
    pass


class ApprovalNotFoundError(CollabError):
    """Approval ID not found in session."""
    pass


class ConflictResolutionRequiredError(CollabError):
    """Human decision required to resolve conflict."""
    pass


class CollabTimeoutError(CollabError):
    """Operation exceeded timeout."""
    pass


class SnapshotCorruptedError(CollabError):
    """Snapshot checksum mismatch."""
    pass


class EventReplayError(CollabError):
    """Error during event replay."""
    pass


# =============================================================================
# EVENT HIERARCHY
# =============================================================================

@dataclass(frozen=True)
class Event:
    """
    Base event class. All events are immutable.

    Events form append-only audit log for event sourcing.
    Each event has a unique ID, type discriminator, timestamp, and session context.
    """
    event_id: str  # UUID
    timestamp: float  # Unix timestamp with millisecond precision
    session_id: str
    event_type: str  # Discriminator for deserialization

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict for persistence."""
        raise NotImplementedError(
            "Subclasses must implement to_dict() for serialization"
        )


@dataclass(frozen=True, kw_only=True)
class ApprovalQueuedEvent(Event):
    """
    Recorded when agent requests command approval.
    First event in approval chain.
    """
    payload: 'ApprovalQueuedEvent.Payload'
    event_type: Literal["approval_queued"] = "approval_queued"

    class Payload(TypedDict):
        approval_id: str  # UUID
        agent_id: str
        command: str  # Original command as requested
        working_dir: str  # Current working directory
        timestamp: float  # When approval requested

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, kw_only=True)
class ApprovalDecidedEvent(Event):
    """
    Recorded when human approves/rejects command.
    Terminal state for approval state machine.
    """
    payload: 'ApprovalDecidedEvent.Payload'
    event_type: Literal["approval_decided"] = "approval_decided"

    class Payload(TypedDict):
        approval_id: str
        status: Literal["approved", "rejected"]  # Terminal states only
        decided_at: float  # Timestamp when decision made
        edited_command: str | None  # If human edited, new command; else None
        decision_note: str | None  # Optional human comment

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, kw_only=True)
class ApprovalExecutedEvent(Event):
    """
    Recorded BEFORE command execution starts.
    Marks approval as "execution in progress".
    Critical for crash recovery idempotence.

    Crash Recovery Semantics:
    - If ApprovalExecutedEvent exists but CommandExecutedEvent missing:
      → Process crashed during execution
      → SKIP re-execution on replay (command may have partial side effects)
    """
    payload: 'ApprovalExecutedEvent.Payload'
    event_type: Literal["approval_executed"] = "approval_executed"

    class Payload(TypedDict):
        approval_id: str
        agent_id: str
        command: str  # Command about to execute (may differ from original if edited)
        execution_started_at: float  # Timestamp when execution began

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, kw_only=True)
class CommandExecutedEvent(Event):
    """
    Recorded AFTER command execution completes.
    Contains full execution results.
    """
    payload: 'CommandExecutedEvent.Payload'
    event_type: Literal["command_executed"] = "command_executed"

    class Payload(TypedDict):
        approval_id: str  # Links to approval chain
        agent_id: str
        command: str
        exit_code: int
        output: str  # Combined stdout+stderr
        working_dir: str  # Working directory at execution time
        timestamp: float  # Execution completion timestamp
        duration_ms: int  # Execution duration in milliseconds

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, kw_only=True)
class FileEditedEvent(Event):
    """
    Recorded when file content changes.

    Context Propagation:
    - approval_id: Non-None if edit resulted from approved shell command
                   None if direct API edit (e.g., agent direct file write)
    - agent_id: Agent that performed edit
    """
    payload: 'FileEditedEvent.Payload'
    event_type: Literal["file_edited"] = "file_edited"

    class Payload(TypedDict):
        file_path: str  # Absolute path
        agent_id: str
        approval_id: str | None  # None if direct API edit, non-None if from approved command
        old_content_hash: str  # SHA256 of previous content
        new_content_hash: str  # SHA256 of new content
        line_range: tuple[int, int] | None  # (start_line, end_line) if line-level edit
        timestamp: float

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        payload_dict = dict(self.payload)
        if payload_dict.get("line_range") is not None:
            payload_dict["line_range"] = list(payload_dict["line_range"])
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": payload_dict,
        }


@dataclass(frozen=True, kw_only=True)
class DirectoryChangedEvent(Event):
    """
    Recorded when agent changes working directory.
    """
    payload: 'DirectoryChangedEvent.Payload'
    event_type: Literal["directory_changed"] = "directory_changed"

    class Payload(TypedDict):
        agent_id: str
        old_cwd: str
        new_cwd: str
        timestamp: float

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, kw_only=True)
class ConflictDetectedEvent(Event):
    """
    Recorded when conflict resolver detects file or directory conflict.
    """
    payload: 'ConflictDetectedEvent.Payload'
    event_type: Literal["conflict_detected"] = "conflict_detected"

    class Payload(TypedDict):
        conflict_type: Literal["file", "directory", "command_sequence"]
        agent_ids: list[str]  # Agents involved in conflict
        resource_path: str  # File path or directory path
        conflict_details: str  # Human-readable description
        resolution_required: bool  # True if human decision needed
        timestamp: float

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, kw_only=True)
class AgentRegisteredEvent(Event):
    """Recorded when agent joins session."""
    payload: 'AgentRegisteredEvent.Payload'
    event_type: Literal["agent_registered"] = "agent_registered"

    class Payload(TypedDict):
        agent_id: str
        capabilities: list[str]  # e.g., ["python_testing", "debugging"]
        metadata: dict[str, str]  # e.g., {"version": "1.0", "model": "claude-3"}
        timestamp: float

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, kw_only=True)
class TaskCreatedEvent(Event):
    """Recorded when new task added to DAG."""
    payload: 'TaskCreatedEvent.Payload'
    event_type: Literal["task_created"] = "task_created"

    class Payload(TypedDict):
        task_id: str
        description: str
        dependencies: list[str]  # List of task_ids this task depends on
        required_capabilities: list[str]
        created_by: str  # agent_id or "system"
        timestamp: float

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, kw_only=True)
class TaskStatusChangedEvent(Event):
    """Recorded when task status transitions."""
    payload: 'TaskStatusChangedEvent.Payload'
    event_type: Literal["task_status_changed"] = "task_status_changed"

    class Payload(TypedDict):
        task_id: str
        old_status: Literal["pending", "running", "completed", "blocked"]
        new_status: Literal["pending", "running", "completed", "blocked"]
        assigned_agent_id: str | None  # Agent assigned to task (if running)
        timestamp: float

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": dict(self.payload),
        }


# =============================================================================
# TYPEDDICTS: CORE DATA STRUCTURES
# =============================================================================

class SessionState(TypedDict):
    """
    Complete session state reconstructed from event log.
    Immutable snapshot at a point in time.
    """
    session_id: str
    agents: dict[str, 'AgentInfo']  # agent_id → AgentInfo
    current_working_dirs: dict[str, str]  # agent_id → cwd path
    tasks: dict[str, 'TaskStatus']  # task_id → TaskStatus
    recent_commands: list['CommandRecord']  # Last 100 commands
    pending_approvals: dict[str, 'ApprovalRequest']  # approval_id → ApprovalRequest
    active_conflicts: dict[str, 'ConflictInfo']  # conflict_id → ConflictInfo
    created_at: float
    last_updated_at: float
    event_count: int  # Number of events in this session


class AgentInfo(TypedDict):
    """Agent metadata and status."""
    agent_id: str
    capabilities: list[str]
    status: Literal["active", "idle", "disconnected"]
    current_task_id: str | None  # None if no task assigned
    joined_at: float
    last_activity_at: float


class ApprovalRequest(TypedDict):
    """
    Approval state machine.

    STATE MACHINE INVARIANTS (ENFORCED IN CODE):
    1. status='pending' → decided_at MUST be None
    2. status in ['approved', 'rejected'] → decided_at MUST be non-None
    3. Atomic transition: Set status first, then decided_at = time.time()
    4. Terminal states: Once 'approved' or 'rejected', state never changes

    TEMPORAL SEMANTICS:
    - decided_at is set EXACTLY when status transitions to terminal state
    - Invariant: (decided_at is not None) ≡ (status in ['approved', 'rejected'])
    """
    approval_id: str
    agent_id: str
    command: str  # Original command
    edited_command: str | None  # Non-None if human edited command
    status: Literal["pending", "approved", "rejected"]  # State machine
    requested_at: float
    decided_at: float | None  # See invariants above
    decision_note: str | None


class TaskStatus(TypedDict):
    """
    Task state in DAG.

    STATE MACHINE INVARIANTS (ENFORCED IN CODE):
    1. status in ['pending', 'blocked'] → assigned_agent_id MUST be None
    2. status='running' → assigned_agent_id MUST be non-None and reference active agent
    3. status='completed' → assigned_agent_id remains set (immutable after assignment)

    VALID STATE TRANSITIONS:
    - pending → running (when assigned to agent)
    - pending → blocked (if dependencies not met)
    - blocked → running (when dependencies satisfied)
    - running → completed (when agent finishes task)

    VALIDATION:
    - AgentCoordinator.schedule_agent_for_task() validates invariants
    - If status='running' and assigned_agent_id is None → raise InvalidTaskStateError
    """
    task_id: str
    description: str
    status: Literal["pending", "running", "completed", "blocked"]
    assigned_agent_id: str | None  # See invariants above
    dependencies: list[str]  # task_ids this task depends on
    required_capabilities: list[str]
    created_at: float
    started_at: float | None  # When status → running
    completed_at: float | None  # When status → completed


class CommandRecord(TypedDict):
    """Historical record of executed command."""
    approval_id: str
    agent_id: str
    command: str
    exit_code: int
    executed_at: float


class ConflictInfo(TypedDict):
    """
    File conflict metadata.

    TYPE SEMANTICS (CRITICAL):
    - ConflictInfo is ONLY returned when conflict EXISTS
    - Therefore, overlapping_lines is ALWAYS non-None and non-empty
    - detect_file_conflict() return type:
      → None: No conflict detected
      → ConflictInfo: Conflict exists, overlapping_lines guaranteed non-empty

    This eliminates type ambiguity: when ConflictInfo is returned,
    overlapping_lines is guaranteed to be a non-empty list.
    """
    conflict_id: str
    file_path: str
    agent_ids: list[str]  # Agents with conflicting edits (length >= 2)
    overlapping_lines: list[tuple[int, int]]  # NON-EMPTY list of (start, end) line ranges
    detected_at: float
    resolved: bool
    resolution_strategy: Literal["auto_merge", "human_decision", "first_write_wins"] | None


class CommandResult(TypedDict):
    """Result of command execution."""
    approval_id: str  # Links to approval chain
    agent_id: str  # Agent that executed command
    command: str
    exit_code: int
    output: str  # Combined stdout+stderr
    working_dir: str
    timestamp: float  # Execution completion timestamp
    duration_ms: int


class SnapshotMetadata(TypedDict):
    """Metadata for snapshot file."""
    session_id: str
    event_count: int  # Number of events at snapshot time
    timestamp: float  # Unix timestamp in milliseconds (13-digit)
    checksum: str  # SHA256 of snapshot content
    compressed: bool  # True if gzip compressed


class DirectoryConflictWarning(TypedDict):
    """Warning when multiple agents change directories."""
    agent_ids: list[str]
    directories: dict[str, str]  # agent_id → new_cwd
    recommendation: str  # Human-readable suggestion


class CommandSequenceWarning(TypedDict):
    """
    Warning for potentially conflicting command sequences.

    INTEGRATION POINT (Addresses tech lead feedback #8):
    Warnings displayed in CLI approval prompt:

    $ collab approve <approval_id>

    ⚠ WARNING: Potential conflict detected
      Agent A: cd /project/frontend
      Agent B: cd /project/backend
      Recommendation: Coordinate directory changes before approval

    [y]es / [n]o / [e]dit / [q]ueue for later?

    Warnings are INFORMATIONAL, not blocking.
    """
    agent_ids: list[str]
    commands: dict[str, str]  # agent_id → command
    conflict_type: Literal["directory_conflict", "file_write_race", "resource_contention"]
    recommendation: str
