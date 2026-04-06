"""
Collaborative Terminal for AI Agents

A human-in-the-loop multi-agent terminal system that enables multiple specialized
AI agents to work together on complex shell tasks under continuous human supervision.
"""

__version__ = "0.1.0"
__author__ = "Collaborative Terminal Team"

from .types import (
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
from .session_manager import SessionManager
from .capability_registry import CapabilityRegistry

__all__ = [
    # Events
    "Event",
    "ApprovalQueuedEvent",
    "ApprovalDecidedEvent",
    "ApprovalExecutedEvent",
    "CommandExecutedEvent",
    "FileEditedEvent",
    "DirectoryChangedEvent",
    "ConflictDetectedEvent",
    "AgentRegisteredEvent",
    "TaskCreatedEvent",
    "TaskStatusChangedEvent",
    # TypedDicts
    "SessionState",
    "AgentInfo",
    "ApprovalRequest",
    "TaskStatus",
    "CommandRecord",
    "ConflictInfo",
    "CommandResult",
    "SnapshotMetadata",
    "DirectoryConflictWarning",
    "CommandSequenceWarning",
    # Exceptions
    "CollabError",
    "InvalidSessionStateError",
    "InvalidTaskStateError",
    "ApprovalNotFoundError",
    "ConflictResolutionRequiredError",
    "CollabTimeoutError",
    "SnapshotCorruptedError",
    "EventReplayError",
    # Classes
    "SessionManager",
    "CapabilityRegistry",
]
