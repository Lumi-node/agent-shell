"""
Unit tests for collab.types module.

Tests cover:
- Event class instantiation and frozen dataclass enforcement
- TypedDict structure validation
- State machine invariants (ApprovalRequest, TaskStatus)
- Exception hierarchy
- Event serialization (to_dict method)
"""

import pytest
import time
from dataclasses import FrozenInstanceError

from collab.types import (
    # Events
    Event,
    ApprovalQueuedEvent,
    ApprovalDecidedEvent,
    ApprovalExecutedEvent,
    CommandExecutedEvent,
    FileEditedEvent,
    DirectoryChangedEvent,
    ConflictDetectedEvent,
    AgentRegisteredEvent,
    TaskCreatedEvent,
    TaskStatusChangedEvent,
    # TypedDicts
    SessionState,
    AgentInfo,
    ApprovalRequest,
    TaskStatus,
    CommandRecord,
    ConflictInfo,
    CommandResult,
    SnapshotMetadata,
    DirectoryConflictWarning,
    CommandSequenceWarning,
    # Exceptions
    CollabError,
    InvalidSessionStateError,
    InvalidTaskStateError,
    ApprovalNotFoundError,
    ConflictResolutionRequiredError,
    CollabTimeoutError,
    SnapshotCorruptedError,
    EventReplayError,
)


# =============================================================================
# APPROVAL QUEUED EVENT TESTS
# =============================================================================

def test_approval_queued_event_creation():
    """Test ApprovalQueuedEvent instantiation with all required fields."""
    now = time.time()
    payload: ApprovalQueuedEvent.Payload = {
        "approval_id": "apr-001",
        "agent_id": "agent-01",
        "command": "pytest tests/",
        "working_dir": "/project",
        "timestamp": now,
    }
    event = ApprovalQueuedEvent(
        event_id="evt-001",
        timestamp=now,
        session_id="sess-001",
        payload=payload,
    )
    assert event.event_id == "evt-001"
    assert event.event_type == "approval_queued"
    assert event.timestamp == now
    assert event.session_id == "sess-001"
    assert event.payload["approval_id"] == "apr-001"
    assert event.payload["agent_id"] == "agent-01"  # type: ignore[index]


def test_approval_queued_event_frozen():
    """Test ApprovalQueuedEvent is immutable (frozen)."""
    now = time.time()
    event = ApprovalQueuedEvent(
        event_id="evt-001",
        timestamp=now,
        session_id="sess-001",
        payload={
            "approval_id": "apr-001",
            "agent_id": "agent-01",
            "command": "pytest tests/",
            "working_dir": "/project",
            "timestamp": now,
        },
    )
    with pytest.raises(FrozenInstanceError):
        event.event_id = "evt-002"


def test_approval_queued_event_to_dict():
    """Test ApprovalQueuedEvent serialization to dict."""
    now = time.time()
    event = ApprovalQueuedEvent(
        event_id="evt-001",
        timestamp=now,
        session_id="sess-001",
        payload={
            "approval_id": "apr-001",
            "agent_id": "agent-01",
            "command": "pytest tests/",
            "working_dir": "/project",
            "timestamp": now,
        },
    )
    d = event.to_dict()
    assert d["event_id"] == "evt-001"
    assert d["event_type"] == "approval_queued"
    assert d["session_id"] == "sess-001"
    assert d["payload"]["approval_id"] == "apr-001"


# =============================================================================
# APPROVAL DECIDED EVENT TESTS
# =============================================================================

def test_approval_decided_event_creation():
    """Test ApprovalDecidedEvent instantiation with all required fields."""
    now = time.time()
    event = ApprovalDecidedEvent(
        event_id="evt-002",
        timestamp=now,
        session_id="sess-001",
        payload={
            "approval_id": "apr-001",
            "status": "approved",
            "decided_at": now,
            "edited_command": None,
            "decision_note": "Looks good",
        },
    )
    assert event.event_type == "approval_decided"
    assert event.payload["status"] == "approved"
    assert event.payload["decided_at"] == now


def test_approval_decided_event_with_edited_command():
    """Test ApprovalDecidedEvent with edited_command populated."""
    now = time.time()
    event = ApprovalDecidedEvent(
        event_id="evt-002",
        timestamp=now,
        session_id="sess-001",
        payload={
            "approval_id": "apr-001",
            "status": "approved",
            "decided_at": now,
            "edited_command": "pytest tests/ -v",
            "decision_note": None,
        },
    )
    assert event.payload["edited_command"] == "pytest tests/ -v"


# =============================================================================
# COMMAND EXECUTED EVENT TESTS
# =============================================================================

def test_command_executed_event_creation():
    """Test CommandExecutedEvent instantiation."""
    now = time.time()
    event = CommandExecutedEvent(
        event_id="evt-003",
        timestamp=now,
        session_id="sess-001",
        payload={
            "approval_id": "apr-001",
            "agent_id": "agent-01",
            "command": "pytest tests/",
            "exit_code": 0,
            "output": "... test output ...",
            "working_dir": "/project",
            "timestamp": now,
            "duration_ms": 5000,
        },
    )
    assert event.event_type == "command_executed"
    assert event.payload["exit_code"] == 0
    assert event.payload["duration_ms"] == 5000


# =============================================================================
# FILE EDITED EVENT TESTS
# =============================================================================

def test_file_edited_event_with_approval_id():
    """Test FileEditedEvent with approval_id set."""
    now = time.time()
    event = FileEditedEvent(
        event_id="evt-004",
        timestamp=now,
        session_id="sess-001",
        payload={
            "file_path": "/project/test.py",
            "agent_id": "agent-01",
            "approval_id": "apr-001",
            "old_content_hash": "abc123",
            "new_content_hash": "def456",
            "line_range": (10, 15),
            "timestamp": now,
        },
    )
    assert event.payload["approval_id"] == "apr-001"
    assert event.payload["line_range"] == (10, 15)


def test_file_edited_event_without_approval_id():
    """Test FileEditedEvent with approval_id as None (direct API edit)."""
    now = time.time()
    event = FileEditedEvent(
        event_id="evt-004",
        timestamp=now,
        session_id="sess-001",
        payload={
            "file_path": "/project/test.py",
            "agent_id": "agent-01",
            "approval_id": None,  # Direct API edit, no approval
            "old_content_hash": "abc123",
            "new_content_hash": "def456",
            "line_range": None,
            "timestamp": now,
        },
    )
    assert event.payload["approval_id"] is None


def test_file_edited_event_to_dict_with_line_range():
    """Test FileEditedEvent serialization preserves line_range as list."""
    now = time.time()
    event = FileEditedEvent(
        event_id="evt-004",
        timestamp=now,
        session_id="sess-001",
        payload={
            "file_path": "/project/test.py",
            "agent_id": "agent-01",
            "approval_id": "apr-001",
            "old_content_hash": "abc123",
            "new_content_hash": "def456",
            "line_range": (10, 15),
            "timestamp": now,
        },
    )
    d = event.to_dict()
    # line_range should be converted to list for JSON serialization
    assert d["payload"]["line_range"] == [10, 15]


# =============================================================================
# DIRECTORY CHANGED EVENT TESTS
# =============================================================================

def test_directory_changed_event_creation():
    """Test DirectoryChangedEvent instantiation."""
    now = time.time()
    event = DirectoryChangedEvent(
        event_id="evt-005",
        timestamp=now,
        session_id="sess-001",
        payload={
            "agent_id": "agent-01",
            "old_cwd": "/project",
            "new_cwd": "/project/tests",
            "timestamp": now,
        },
    )
    assert event.event_type == "directory_changed"
    assert event.payload["new_cwd"] == "/project/tests"


# =============================================================================
# CONFLICT DETECTED EVENT TESTS
# =============================================================================

def test_conflict_detected_event_creation():
    """Test ConflictDetectedEvent instantiation."""
    now = time.time()
    event = ConflictDetectedEvent(
        event_id="evt-006",
        timestamp=now,
        session_id="sess-001",
        payload={
            "conflict_type": "file",
            "agent_ids": ["agent-01", "agent-02"],
            "resource_path": "/project/test.py",
            "conflict_details": "Both agents modified lines 10-15",
            "resolution_required": True,
            "timestamp": now,
        },
    )
    assert event.event_type == "conflict_detected"
    assert event.payload["conflict_type"] == "file"


# =============================================================================
# AGENT REGISTERED EVENT TESTS
# =============================================================================

def test_agent_registered_event_creation():
    """Test AgentRegisteredEvent instantiation."""
    now = time.time()
    event = AgentRegisteredEvent(
        event_id="evt-007",
        timestamp=now,
        session_id="sess-001",
        payload={
            "agent_id": "agent-01",
            "capabilities": ["python_testing", "debugging"],
            "metadata": {"version": "1.0", "model": "claude-3"},
            "timestamp": now,
        },
    )
    assert event.event_type == "agent_registered"
    assert "python_testing" in event.payload["capabilities"]


# =============================================================================
# TASK CREATED EVENT TESTS
# =============================================================================

def test_task_created_event_creation():
    """Test TaskCreatedEvent instantiation."""
    now = time.time()
    event = TaskCreatedEvent(
        event_id="evt-008",
        timestamp=now,
        session_id="sess-001",
        payload={
            "task_id": "task-001",
            "description": "Debug test failure",
            "dependencies": [],
            "required_capabilities": ["python_testing"],
            "created_by": "agent-01",
            "timestamp": now,
        },
    )
    assert event.event_type == "task_created"
    assert event.payload["task_id"] == "task-001"


def test_task_created_event_with_dependencies():
    """Test TaskCreatedEvent with dependencies."""
    now = time.time()
    event = TaskCreatedEvent(
        event_id="evt-008",
        timestamp=now,
        session_id="sess-001",
        payload={
            "task_id": "task-002",
            "description": "Analyze results",
            "dependencies": ["task-001"],
            "required_capabilities": ["debugging"],
            "created_by": "system",
            "timestamp": now,
        },
    )
    assert event.payload["dependencies"] == ["task-001"]


# =============================================================================
# TASK STATUS CHANGED EVENT TESTS
# =============================================================================

def test_task_status_changed_event_pending_to_running():
    """Test TaskStatusChangedEvent for pending → running transition."""
    now = time.time()
    event = TaskStatusChangedEvent(
        event_id="evt-009",
        timestamp=now,
        session_id="sess-001",
        payload={
            "task_id": "task-001",
            "old_status": "pending",
            "new_status": "running",
            "assigned_agent_id": "agent-01",
            "timestamp": now,
        },
    )
    assert event.event_type == "task_status_changed"
    assert event.payload["new_status"] == "running"
    assert event.payload["assigned_agent_id"] == "agent-01"


def test_task_status_changed_event_running_to_completed():
    """Test TaskStatusChangedEvent for running → completed transition."""
    now = time.time()
    event = TaskStatusChangedEvent(
        event_id="evt-009",
        timestamp=now,
        session_id="sess-001",
        payload={
            "task_id": "task-001",
            "old_status": "running",
            "new_status": "completed",
            "assigned_agent_id": "agent-01",
            "timestamp": now,
        },
    )
    assert event.payload["new_status"] == "completed"


# =============================================================================
# APPROVAL REQUEST STATE MACHINE INVARIANTS
# =============================================================================

def test_approval_request_pending_has_no_decided_at():
    """
    ApprovalRequest state machine invariant:
    status='pending' → decided_at MUST be None
    """
    approval: ApprovalRequest = {
        "approval_id": "apr-001",
        "agent_id": "agent-01",
        "command": "pytest tests/",
        "edited_command": None,
        "status": "pending",
        "requested_at": time.time(),
        "decided_at": None,  # Must be None for pending status
        "decision_note": None,
    }
    assert approval["status"] == "pending"
    assert approval["decided_at"] is None


def test_approval_request_approved_has_decided_at():
    """
    ApprovalRequest state machine invariant:
    status='approved' → decided_at MUST be non-None
    """
    now = time.time()
    approval: ApprovalRequest = {
        "approval_id": "apr-001",
        "agent_id": "agent-01",
        "command": "pytest tests/",
        "edited_command": None,
        "status": "approved",
        "requested_at": time.time(),
        "decided_at": now,  # Must be non-None for approved status
        "decision_note": None,
    }
    assert approval["status"] == "approved"
    assert approval["decided_at"] is not None
    assert approval["decided_at"] == now


def test_approval_request_rejected_has_decided_at():
    """
    ApprovalRequest state machine invariant:
    status='rejected' → decided_at MUST be non-None
    """
    now = time.time()
    approval: ApprovalRequest = {
        "approval_id": "apr-001",
        "agent_id": "agent-01",
        "command": "pytest tests/",
        "edited_command": None,
        "status": "rejected",
        "requested_at": time.time(),
        "decided_at": now,  # Must be non-None for rejected status
        "decision_note": "Unsafe command",
    }
    assert approval["status"] == "rejected"
    assert approval["decided_at"] is not None


# =============================================================================
# TASK STATUS STATE MACHINE INVARIANTS
# =============================================================================

def test_task_status_pending_has_no_assigned_agent():
    """
    TaskStatus state machine invariant:
    status='pending' → assigned_agent_id MUST be None
    """
    now = time.time()
    task: TaskStatus = {
        "task_id": "task-001",
        "description": "Debug test failure",
        "status": "pending",
        "assigned_agent_id": None,  # Must be None for pending status
        "dependencies": [],
        "required_capabilities": ["python_testing"],
        "created_at": now,
        "started_at": None,
        "completed_at": None,
    }
    assert task["status"] == "pending"
    assert task["assigned_agent_id"] is None


def test_task_status_blocked_has_no_assigned_agent():
    """
    TaskStatus state machine invariant:
    status='blocked' → assigned_agent_id MUST be None
    """
    now = time.time()
    task: TaskStatus = {
        "task_id": "task-002",
        "description": "Analyze results",
        "status": "blocked",
        "assigned_agent_id": None,  # Must be None for blocked status
        "dependencies": ["task-001"],
        "required_capabilities": ["debugging"],
        "created_at": now,
        "started_at": None,
        "completed_at": None,
    }
    assert task["status"] == "blocked"
    assert task["assigned_agent_id"] is None


def test_task_status_running_has_assigned_agent():
    """
    TaskStatus state machine invariant:
    status='running' → assigned_agent_id MUST be non-None
    """
    now = time.time()
    task: TaskStatus = {
        "task_id": "task-001",
        "description": "Debug test failure",
        "status": "running",
        "assigned_agent_id": "agent-01",  # Must be non-None for running status
        "dependencies": [],
        "required_capabilities": ["python_testing"],
        "created_at": now,
        "started_at": now,
        "completed_at": None,
    }
    assert task["status"] == "running"
    assert task["assigned_agent_id"] is not None


def test_task_status_completed_immutable_agent_id():
    """
    TaskStatus state machine invariant:
    status='completed' → assigned_agent_id remains set and immutable
    """
    now = time.time()
    task: TaskStatus = {
        "task_id": "task-001",
        "description": "Debug test failure",
        "status": "completed",
        "assigned_agent_id": "agent-01",  # Immutable after completion
        "dependencies": [],
        "required_capabilities": ["python_testing"],
        "created_at": now,
        "started_at": now,
        "completed_at": now + 100,
    }
    assert task["status"] == "completed"
    assert task["assigned_agent_id"] == "agent-01"


# =============================================================================
# CONFLICT INFO TESTS
# =============================================================================

def test_conflict_info_overlapping_lines_non_empty():
    """
    ConflictInfo type semantics:
    overlapping_lines is ALWAYS non-None and non-empty when ConflictInfo returned.
    """
    now = time.time()
    conflict: ConflictInfo = {
        "conflict_id": "conf-001",
        "file_path": "/project/test.py",
        "agent_ids": ["agent-01", "agent-02"],
        "overlapping_lines": [(10, 15)],  # NON-EMPTY list
        "detected_at": now,
        "resolved": False,
        "resolution_strategy": None,
    }
    assert len(conflict["overlapping_lines"]) > 0
    assert conflict["overlapping_lines"][0] == (10, 15)


def test_conflict_info_multiple_overlapping_ranges():
    """Test ConflictInfo with multiple overlapping line ranges."""
    now = time.time()
    conflict: ConflictInfo = {
        "conflict_id": "conf-001",
        "file_path": "/project/test.py",
        "agent_ids": ["agent-01", "agent-02"],
        "overlapping_lines": [(5, 10), (15, 20)],  # Multiple ranges
        "detected_at": now,
        "resolved": False,
        "resolution_strategy": None,
    }
    assert len(conflict["overlapping_lines"]) == 2


# =============================================================================
# COMMAND RECORD TESTS
# =============================================================================

def test_command_record_creation():
    """Test CommandRecord instantiation."""
    now = time.time()
    record: CommandRecord = {
        "approval_id": "apr-001",
        "agent_id": "agent-01",
        "command": "pytest tests/",
        "exit_code": 0,
        "executed_at": now,
    }
    assert record["command"] == "pytest tests/"
    assert record["exit_code"] == 0


# =============================================================================
# COMMAND RESULT TESTS
# =============================================================================

def test_command_result_creation():
    """Test CommandResult instantiation."""
    now = time.time()
    result: CommandResult = {
        "approval_id": "apr-001",
        "agent_id": "agent-01",
        "command": "pytest tests/",
        "exit_code": 0,
        "output": ".... passed",
        "working_dir": "/project",
        "timestamp": now,
        "duration_ms": 5000,
    }
    assert result["exit_code"] == 0
    assert result["duration_ms"] == 5000


# =============================================================================
# SNAPSHOT METADATA TESTS
# =============================================================================

def test_snapshot_metadata_creation():
    """Test SnapshotMetadata instantiation."""
    now_ms = int(time.time() * 1000)  # 13-digit millisecond timestamp
    metadata: SnapshotMetadata = {
        "session_id": "sess-001",
        "event_count": 100,
        "timestamp": now_ms,
        "checksum": "abc123def456",
        "compressed": True,
    }
    assert metadata["event_count"] == 100
    assert metadata["compressed"] is True


# =============================================================================
# EXCEPTION HIERARCHY TESTS
# =============================================================================

def test_collab_error_base_exception():
    """Test CollabError base exception."""
    with pytest.raises(CollabError):
        raise CollabError("Base error")


def test_invalid_session_state_error_inheritance():
    """Test InvalidSessionStateError inherits from CollabError."""
    with pytest.raises(CollabError):
        raise InvalidSessionStateError("Session state invalid")


def test_invalid_task_state_error_inheritance():
    """Test InvalidTaskStateError inherits from CollabError."""
    with pytest.raises(CollabError):
        raise InvalidTaskStateError("Task state invalid")


def test_approval_not_found_error_inheritance():
    """Test ApprovalNotFoundError inherits from CollabError."""
    with pytest.raises(CollabError):
        raise ApprovalNotFoundError("Approval not found")


def test_conflict_resolution_required_error_inheritance():
    """Test ConflictResolutionRequiredError inherits from CollabError."""
    with pytest.raises(CollabError):
        raise ConflictResolutionRequiredError("Human decision required")


def test_collab_timeout_error_inheritance():
    """Test CollabTimeoutError inherits from CollabError."""
    with pytest.raises(CollabError):
        raise CollabTimeoutError("Operation timed out")


def test_snapshot_corrupted_error_inheritance():
    """Test SnapshotCorruptedError inherits from CollabError."""
    with pytest.raises(CollabError):
        raise SnapshotCorruptedError("Snapshot checksum mismatch")


def test_event_replay_error_inheritance():
    """Test EventReplayError inherits from CollabError."""
    with pytest.raises(CollabError):
        raise EventReplayError("Error during replay")


# =============================================================================
# AGENT INFO TESTS
# =============================================================================

def test_agent_info_creation():
    """Test AgentInfo instantiation."""
    now = time.time()
    agent: AgentInfo = {
        "agent_id": "agent-01",
        "capabilities": ["python_testing", "debugging"],
        "status": "active",
        "current_task_id": "task-001",
        "joined_at": now,
        "last_activity_at": now,
    }
    assert agent["agent_id"] == "agent-01"
    assert agent["status"] == "active"


def test_agent_info_idle_status():
    """Test AgentInfo with idle status."""
    now = time.time()
    agent: AgentInfo = {
        "agent_id": "agent-02",
        "capabilities": [],
        "status": "idle",
        "current_task_id": None,
        "joined_at": now,
        "last_activity_at": now,
    }
    assert agent["status"] == "idle"
    assert agent["current_task_id"] is None


# =============================================================================
# SESSION STATE TESTS
# =============================================================================

def test_session_state_creation():
    """Test SessionState instantiation."""
    now = time.time()
    state: SessionState = {
        "session_id": "sess-001",
        "agents": {},
        "current_working_dirs": {},
        "tasks": {},
        "recent_commands": [],
        "pending_approvals": {},
        "active_conflicts": {},
        "created_at": now,
        "last_updated_at": now,
        "event_count": 0,
    }
    assert state["session_id"] == "sess-001"
    assert state["event_count"] == 0


# =============================================================================
# DIRECTORY CONFLICT WARNING TESTS
# =============================================================================

def test_directory_conflict_warning_creation():
    """Test DirectoryConflictWarning instantiation."""
    warning: DirectoryConflictWarning = {
        "agent_ids": ["agent-01", "agent-02"],
        "directories": {"agent-01": "/project/frontend", "agent-02": "/project/backend"},
        "recommendation": "Coordinate directory changes before approval",
    }
    assert len(warning["agent_ids"]) == 2
    assert warning["directories"]["agent-01"] == "/project/frontend"


# =============================================================================
# COMMAND SEQUENCE WARNING TESTS
# =============================================================================

def test_command_sequence_warning_creation():
    """Test CommandSequenceWarning instantiation."""
    warning: CommandSequenceWarning = {
        "agent_ids": ["agent-01", "agent-02"],
        "commands": {
            "agent-01": "cd /project/frontend",
            "agent-02": "cd /project/backend",
        },
        "conflict_type": "directory_conflict",
        "recommendation": "Coordinate directory changes before approval",
    }
    assert warning["conflict_type"] == "directory_conflict"
    assert warning["recommendation"] is not None


# =============================================================================
# ALL EVENTS FROZEN TEST
# =============================================================================

def test_all_events_frozen():
    """Test that all event types are frozen (immutable)."""
    now = time.time()
    events = [
        ApprovalQueuedEvent(
            event_id="evt-001",
            timestamp=now,
            session_id="sess-001",
            payload={
                "approval_id": "apr-001",
                "agent_id": "agent-01",
                "command": "pytest",
                "working_dir": "/project",
                "timestamp": now,
            },
        ),
        ApprovalDecidedEvent(
            event_id="evt-002",
            timestamp=now,
            session_id="sess-001",
            payload={
                "approval_id": "apr-001",
                "status": "approved",
                "decided_at": now,
                "edited_command": None,
                "decision_note": None,
            },
        ),
        CommandExecutedEvent(
            event_id="evt-003",
            timestamp=now,
            session_id="sess-001",
            payload={
                "approval_id": "apr-001",
                "agent_id": "agent-01",
                "command": "pytest",
                "exit_code": 0,
                "output": "passed",
                "working_dir": "/project",
                "timestamp": now,
                "duration_ms": 1000,
            },
        ),
    ]
    for event in events:
        with pytest.raises(FrozenInstanceError):
            event.event_id = "modified"


# =============================================================================
# EVENT DISCRIMINATOR TESTS
# =============================================================================

def test_event_type_discriminators():
    """Test that event_type field matches class name convention."""
    now = time.time()

    events_and_types = [
        (
            ApprovalQueuedEvent(
                event_id="evt",
                timestamp=now,
                session_id="sess",
                payload={
                    "approval_id": "apr",
                    "agent_id": "agent",
                    "command": "cmd",
                    "working_dir": "/",
                    "timestamp": now,
                },
            ),
            "approval_queued",
        ),
        (
            ApprovalDecidedEvent(
                event_id="evt",
                timestamp=now,
                session_id="sess",
                payload={
                    "approval_id": "apr",
                    "status": "approved",
                    "decided_at": now,
                    "edited_command": None,
                    "decision_note": None,
                },
            ),
            "approval_decided",
        ),
        (
            CommandExecutedEvent(
                event_id="evt",
                timestamp=now,
                session_id="sess",
                payload={
                    "approval_id": "apr",
                    "agent_id": "agent",
                    "command": "cmd",
                    "exit_code": 0,
                    "output": "",
                    "working_dir": "/",
                    "timestamp": now,
                    "duration_ms": 0,
                },
            ),
            "command_executed",
        ),
        (
            DirectoryChangedEvent(
                event_id="evt",
                timestamp=now,
                session_id="sess",
                payload={
                    "agent_id": "agent",
                    "old_cwd": "/",
                    "new_cwd": "/tmp",
                    "timestamp": now,
                },
            ),
            "directory_changed",
        ),
        (
            AgentRegisteredEvent(
                event_id="evt",
                timestamp=now,
                session_id="sess",
                payload={
                    "agent_id": "agent",
                    "capabilities": [],
                    "metadata": {},
                    "timestamp": now,
                },
            ),
            "agent_registered",
        ),
        (
            TaskCreatedEvent(
                event_id="evt",
                timestamp=now,
                session_id="sess",
                payload={
                    "task_id": "task",
                    "description": "desc",
                    "dependencies": [],
                    "required_capabilities": [],
                    "created_by": "system",
                    "timestamp": now,
                },
            ),
            "task_created",
        ),
        (
            TaskStatusChangedEvent(
                event_id="evt",
                timestamp=now,
                session_id="sess",
                payload={
                    "task_id": "task",
                    "old_status": "pending",
                    "new_status": "running",
                    "assigned_agent_id": "agent",
                    "timestamp": now,
                },
            ),
            "task_status_changed",
        ),
    ]

    for event, expected_type in events_and_types:
        assert event.event_type == expected_type, (
            f"Event {event.__class__.__name__} has event_type={event.event_type}, "
            f"expected {expected_type}"
        )
