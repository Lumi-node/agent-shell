"""
Session Manager: Event Sourcing and State Management

Maintains an append-only event log with snapshot compression.
Reconstructs complete session state via snapshot + event replay.
Supports deterministic crash recovery and state querying.
"""

import json
import os
import gzip
import hashlib
import time
import uuid
import re
from pathlib import Path
from typing import Optional

from .types import (
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
    SessionState,
    AgentInfo,
    ApprovalRequest,
    TaskStatus,
    CommandRecord,
    ConflictInfo,
    SnapshotMetadata,
    InvalidSessionStateError,
    SnapshotCorruptedError,
    EventReplayError,
)


class SessionManager:
    """
    Event sourcing engine for collaborative terminal sessions.

    Responsibilities:
    - Append immutable events to events.log
    - Reconstruct SessionState from snapshot + event replay
    - Compress snapshots with gzip
    - Support deterministic crash recovery
    - Query session state (agents, cwd, recent commands)

    Session Structure:
    {session_dir}/
        events.log (append-only JSON lines)
        snapshots/
            snapshot-{unix_time_ms}.bin (gzip-compressed snapshots)
    """

    SNAPSHOT_INTERVAL = 100  # Create snapshot every N events
    SNAPSHOT_REGEX = re.compile(r'snapshot-([\d.]+)\.bin')

    def __init__(self, session_name: str, persist_dir: str) -> None:
        """
        Initialize or load session from disk.

        Creates session directory structure:
        - {persist_dir}/{session_name}/events.log
        - {persist_dir}/{session_name}/snapshots/

        Args:
            session_name: Unique session identifier
            persist_dir: Directory to store session data

        Raises:
            OSError: If directory creation fails
        """
        self.session_name = session_name
        self.persist_dir = Path(persist_dir)
        self.session_dir = self.persist_dir / session_name
        self.events_log_path = self.session_dir / "events.log"
        self.snapshots_dir = self.session_dir / "snapshots"

        # Create session directory structure
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        # Session ID from name (or stored in first event)
        self.session_id = session_name

        # In-memory state cache (rebuilt on load)
        self._state: Optional[SessionState] = None
        self._events_cache: list[Event] = []
        self._last_snapshot_timestamp: Optional[float] = None

    def record_event(
        self,
        event_type: str,
        agent_id: str,
        payload: dict,
    ) -> None:
        """
        Append immutable event to events.log.

        Generates UUID event_id and Unix timestamp (millisecond precision).
        Serializes to JSON line and appends to events.log.

        Raises:
            IOError: If write to events.log fails
            EventReplayError: If event serialization fails
        """
        event_id = str(uuid.uuid4())
        timestamp = time.time()

        # Build event object based on type
        event = self._build_event(
            event_id=event_id,
            event_type=event_type,
            timestamp=timestamp,
            agent_id=agent_id,
            payload=payload,
        )

        # Serialize and append to log
        event_dict = event.to_dict()
        json_line = json.dumps(event_dict)

        try:
            with open(self.events_log_path, "a") as f:
                f.write(json_line + "\n")
        except IOError as e:
            raise EventReplayError(f"Failed to write event to log: {e}")

        # Invalidate state cache (will be rebuilt on next get_session_state)
        self._state = None
        self._events_cache.append(event)

    def get_session_state(self) -> SessionState:
        """
        Return complete SessionState reconstructed from snapshot+replay or full replay.

        If a snapshot exists:
        1. Load latest snapshot
        2. Replay events after snapshot timestamp
        3. Return reconstructed state

        If no snapshot:
        1. Replay all events from beginning
        2. Return reconstructed state

        Returns:
            SessionState with agents, working_dirs, commands, etc.

        Raises:
            EventReplayError: If replay fails
            SnapshotCorruptedError: If snapshot corrupted
        """
        if self._state is not None:
            return self._state

        # Load all events from log
        all_events = self._load_events_from_log()

        # Load snapshot if available
        snapshot_state = self._load_latest_snapshot()
        start_event_idx = 0

        if snapshot_state is not None:
            self._state = snapshot_state
            self._last_snapshot_timestamp = snapshot_state["last_updated_at"]
            # Find events after snapshot timestamp
            for idx, event in enumerate(all_events):
                if event.timestamp > self._last_snapshot_timestamp:
                    start_event_idx = idx
                    break
            else:
                # All events were in snapshot
                start_event_idx = len(all_events)
        else:
            # Full replay from beginning
            self._state = self._initial_state()

        # Replay remaining events
        for event in all_events[start_event_idx:]:
            self._apply_event(self._state, event)

        self._events_cache = all_events
        return self._state

    def set_cwd(self, agent_id: str, new_cwd: str) -> None:
        """
        Record DirectoryChangedEvent for agent working directory.

        Updates agent's current working directory and records event.

        Args:
            agent_id: Agent changing directory
            new_cwd: New working directory path

        Raises:
            EventReplayError: If event recording fails
        """
        # Get current cwd for old_cwd field
        current_state = self.get_session_state()
        old_cwd = current_state.get("current_working_dirs", {}).get(agent_id, "/")

        payload = {
            "agent_id": agent_id,
            "old_cwd": old_cwd,
            "new_cwd": new_cwd,
            "timestamp": time.time(),
        }

        self.record_event("directory_changed", agent_id, payload)

    def get_cwd(self, agent_id: Optional[str] = None) -> str:
        """
        Return current working directory for agent.

        If agent_id is None, returns default (first agent or "/").

        Args:
            agent_id: Agent to query, or None for default

        Returns:
            Current working directory path
        """
        state = self.get_session_state()
        cwd_dict = state.get("current_working_dirs", {})

        if agent_id is None:
            # Return first agent's cwd or default
            if cwd_dict:
                return list(cwd_dict.values())[0]
            return "/"

        return cwd_dict.get(agent_id, "/")

    def get_recent_commands(self, limit: int = 10) -> list[CommandRecord]:
        """
        Return list of CommandRecord sorted chronologically, respecting limit.

        Args:
            limit: Maximum number of commands to return

        Returns:
            List of CommandRecord, most recent last
        """
        state = self.get_session_state()
        commands = state.get("recent_commands", [])
        return commands[-limit:] if len(commands) > limit else commands

    def list_agents(self) -> dict[str, AgentInfo]:
        """
        Return dict of active agents from session state.

        Returns:
            Dict mapping agent_id -> AgentInfo
        """
        state = self.get_session_state()
        return state.get("agents", {})

    def persist_snapshot(self) -> None:
        r"""
        Write gzip-compressed snapshot to snapshots/snapshot-{unix_time_precise}.bin.

        Filename uses full-precision timestamp for sortability and accuracy.
        Example: snapshot-1775432062.4344041.bin
        Regex: r'snapshot-([\d.]+)\.bin'

        Snapshot contains serialized SessionState for fast recovery.

        Raises:
            IOError: If snapshot write fails
            SnapshotCorruptedError: If compression fails
        """
        state = self.get_session_state()

        # Use full-precision timestamp from state
        timestamp_precise = state["last_updated_at"]
        snapshot_filename = f"snapshot-{timestamp_precise}.bin"
        snapshot_path = self.snapshots_dir / snapshot_filename

        try:
            # Serialize state to JSON
            state_json = json.dumps(state, indent=2).encode("utf-8")

            # Compute checksum before compression
            checksum = hashlib.sha256(state_json).hexdigest()

            # Gzip compress
            with gzip.open(snapshot_path, "wb") as f:
                f.write(state_json)

            self._last_snapshot_timestamp = state["last_updated_at"]
        except Exception as e:
            raise SnapshotCorruptedError(f"Failed to persist snapshot: {e}")

    def replay_from_snapshot(self, snapshot_timestamp: float) -> SessionState:
        """
        Load snapshot by timestamp, replay events after timestamp, return state.

        Args:
            snapshot_timestamp: Unix timestamp (full precision) of snapshot to load

        Returns:
            Reconstructed SessionState with replayed events

        Raises:
            SnapshotCorruptedError: If snapshot missing or corrupted
            EventReplayError: If replay fails
        """
        # Find snapshot with timestamp <= target
        snapshots = self._find_snapshots()
        selected_snapshot = None

        for snap_timestamp, snap_path in snapshots:
            if snap_timestamp <= snapshot_timestamp:
                selected_snapshot = snap_path
            else:
                break

        if selected_snapshot is None:
            raise SnapshotCorruptedError(
                f"No snapshot found for timestamp {snapshot_timestamp}"
            )

        # Load and decompress snapshot
        try:
            with gzip.open(selected_snapshot, "rb") as f:
                state_json = f.read().decode("utf-8")
            state = json.loads(state_json)
        except Exception as e:
            raise SnapshotCorruptedError(f"Failed to load snapshot: {e}")

        # Reload all events and find those after snapshot timestamp
        all_events = self._load_events_from_log()
        for event in all_events:
            if event.timestamp > snapshot_timestamp:
                self._apply_event(state, event)

        return state

    def record_file_edit(
        self,
        file_path: str,
        agent_id: str,
        old_content: str,
        new_content: str,
    ) -> None:
        """
        Record FileEditedEvent with SHA256 hashes and line ranges.

        Computes:
        - old_content_hash: SHA256(old_content)
        - new_content_hash: SHA256(new_content)
        - line_range: (start_line, end_line) by diffing

        Args:
            file_path: Absolute path to file
            agent_id: Agent performing edit
            old_content: Previous file content
            new_content: New file content

        Raises:
            EventReplayError: If event recording fails
        """
        old_hash = hashlib.sha256(old_content.encode("utf-8")).hexdigest()
        new_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

        # Calculate line range for the edit
        line_range = self._compute_line_range(old_content, new_content)

        payload = {
            "file_path": file_path,
            "agent_id": agent_id,
            "approval_id": None,  # Direct API edit
            "old_content_hash": old_hash,
            "new_content_hash": new_hash,
            "line_range": line_range,
            "timestamp": time.time(),
        }

        self.record_event("file_edited", agent_id, payload)

    # =========================================================================
    # INTERNAL METHODS
    # =========================================================================

    def _build_event(
        self,
        event_id: str,
        event_type: str,
        timestamp: float,
        agent_id: str,
        payload: dict,
    ) -> Event:
        """Build typed Event object from raw data."""
        base_kwargs = {
            "event_id": event_id,
            "timestamp": timestamp,
            "session_id": self.session_id,
        }

        if event_type == "approval_queued":
            return ApprovalQueuedEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        elif event_type == "approval_decided":
            return ApprovalDecidedEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        elif event_type == "approval_executed":
            return ApprovalExecutedEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        elif event_type == "command_executed":
            return CommandExecutedEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        elif event_type == "file_edited":
            return FileEditedEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        elif event_type == "directory_changed":
            return DirectoryChangedEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        elif event_type == "conflict_detected":
            return ConflictDetectedEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        elif event_type == "agent_registered":
            return AgentRegisteredEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        elif event_type == "task_created":
            return TaskCreatedEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        elif event_type == "task_status_changed":
            return TaskStatusChangedEvent(
                payload=payload,  # type: ignore
                **base_kwargs,
            )
        else:
            raise EventReplayError(f"Unknown event type: {event_type}")

    def _load_events_from_log(self) -> list[Event]:
        """Load all events from events.log."""
        events = []

        if not self.events_log_path.exists():
            return events

        try:
            with open(self.events_log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    event_dict = json.loads(line)
                    event = self._deserialize_event(event_dict)
                    events.append(event)
        except (IOError, json.JSONDecodeError) as e:
            raise EventReplayError(f"Failed to load events: {e}")

        return events

    def _deserialize_event(self, event_dict: dict) -> Event:
        """Deserialize event from JSON dict."""
        event_type = event_dict.get("event_type")
        event_id = event_dict.get("event_id")
        timestamp = event_dict.get("timestamp")
        session_id = event_dict.get("session_id")
        payload = event_dict.get("payload", {})

        # Extract agent_id from payload or use empty string
        agent_id = payload.get("agent_id", "")

        return self._build_event(
            event_id=event_id,
            event_type=event_type,
            timestamp=timestamp,
            agent_id=agent_id,
            payload=payload,
        )

    def _load_latest_snapshot(self) -> Optional[SessionState]:
        """Load latest snapshot if available."""
        snapshots = self._find_snapshots()
        if not snapshots:
            return None

        # Load the most recent snapshot
        _, latest_snapshot_path = snapshots[-1]

        try:
            with gzip.open(latest_snapshot_path, "rb") as f:
                state_json = f.read().decode("utf-8")
            return json.loads(state_json)
        except Exception as e:
            raise SnapshotCorruptedError(f"Failed to load snapshot: {e}")

    def _find_snapshots(self) -> list[tuple[float, Path]]:
        """Find all snapshot files, return sorted by timestamp."""
        snapshots = []

        if not self.snapshots_dir.exists():
            return snapshots

        for file in self.snapshots_dir.iterdir():
            match = self.SNAPSHOT_REGEX.match(file.name)
            if match:
                timestamp_str = match.group(1)
                try:
                    timestamp = float(timestamp_str)
                    snapshots.append((timestamp, file))
                except ValueError:
                    # Skip malformed snapshot filenames
                    continue

        # Sort by timestamp
        snapshots.sort(key=lambda x: x[0])
        return snapshots

    def _initial_state(self) -> SessionState:
        """Create initial empty SessionState."""
        now = time.time()
        return SessionState(
            session_id=self.session_id,
            agents={},
            current_working_dirs={},
            tasks={},
            recent_commands=[],
            pending_approvals={},
            active_conflicts={},
            created_at=now,
            last_updated_at=now,
            event_count=0,
        )

    def _apply_event(self, state: SessionState, event: Event) -> None:
        """Apply event to state, updating all fields."""
        state["event_count"] = state.get("event_count", 0) + 1
        state["last_updated_at"] = event.timestamp

        if isinstance(event, AgentRegisteredEvent):
            payload = event.payload
            agent_info: AgentInfo = {
                "agent_id": payload["agent_id"],
                "capabilities": payload["capabilities"],
                "status": "active",
                "current_task_id": None,
                "joined_at": payload["timestamp"],
                "last_activity_at": payload["timestamp"],
            }
            state["agents"][payload["agent_id"]] = agent_info
            if payload["agent_id"] not in state["current_working_dirs"]:
                state["current_working_dirs"][payload["agent_id"]] = "/"

        elif isinstance(event, CommandExecutedEvent):
            payload = event.payload
            command_record: CommandRecord = {
                "approval_id": payload["approval_id"],
                "agent_id": payload["agent_id"],
                "command": payload["command"],
                "exit_code": payload["exit_code"],
                "executed_at": payload["timestamp"],
            }
            state["recent_commands"].append(command_record)
            # Keep last 100 commands
            if len(state["recent_commands"]) > 100:
                state["recent_commands"] = state["recent_commands"][-100:]

            # Update agent's working directory if different
            if payload["working_dir"]:
                state["current_working_dirs"][payload["agent_id"]] = payload[
                    "working_dir"
                ]

        elif isinstance(event, DirectoryChangedEvent):
            payload = event.payload
            state["current_working_dirs"][payload["agent_id"]] = payload["new_cwd"]

        elif isinstance(event, ApprovalQueuedEvent):
            payload = event.payload
            approval_request: ApprovalRequest = {
                "approval_id": payload["approval_id"],
                "agent_id": payload["agent_id"],
                "command": payload["command"],
                "edited_command": None,
                "status": "pending",
                "requested_at": payload["timestamp"],
                "decided_at": None,
                "decision_note": None,
            }
            state["pending_approvals"][payload["approval_id"]] = approval_request

        elif isinstance(event, ApprovalDecidedEvent):
            payload = event.payload
            if payload["approval_id"] in state["pending_approvals"]:
                approval = state["pending_approvals"][payload["approval_id"]]
                approval["status"] = payload["status"]
                approval["decided_at"] = payload["decided_at"]
                approval["edited_command"] = payload["edited_command"]
                approval["decision_note"] = payload["decision_note"]

        elif isinstance(event, FileEditedEvent):
            # File edits are recorded but don't change session state directly
            # They are tracked for conflict detection by downstream components
            pass

        elif isinstance(event, ConflictDetectedEvent):
            payload = event.payload
            conflict_id = event.event_id  # Use event_id as conflict_id
            conflict_info: ConflictInfo = {
                "conflict_id": conflict_id,
                "file_path": payload["resource_path"],
                "agent_ids": payload["agent_ids"],
                "overlapping_lines": [],  # Will be populated by conflict resolver
                "detected_at": event.timestamp,
                "resolved": False,
                "resolution_strategy": None,
            }
            state["active_conflicts"][conflict_id] = conflict_info

        elif isinstance(event, TaskCreatedEvent):
            payload = event.payload
            task_status: TaskStatus = {
                "task_id": payload["task_id"],
                "description": payload["description"],
                "status": "pending",
                "assigned_agent_id": None,
                "dependencies": payload["dependencies"],
                "required_capabilities": payload["required_capabilities"],
                "created_at": payload["timestamp"],
                "started_at": None,
                "completed_at": None,
            }
            state["tasks"][payload["task_id"]] = task_status

        elif isinstance(event, TaskStatusChangedEvent):
            payload = event.payload
            if payload["task_id"] in state["tasks"]:
                task = state["tasks"][payload["task_id"]]
                task["status"] = payload["new_status"]
                if payload["new_status"] == "running":
                    task["assigned_agent_id"] = payload["assigned_agent_id"]
                    task["started_at"] = event.timestamp
                elif payload["new_status"] == "completed":
                    task["completed_at"] = event.timestamp

    def _compute_line_range(
        self, old_content: str, new_content: str
    ) -> Optional[tuple[int, int]]:
        """
        Compute (start_line, end_line) for the edit.

        Returns None if entire file was replaced, or (start, end) tuple.
        """
        old_lines = old_content.split("\n")
        new_lines = new_content.split("\n")

        if len(old_lines) == 0 or len(new_lines) == 0:
            return None

        # Find first differing line
        start_line = 0
        for i, (old_line, new_line) in enumerate(zip(old_lines, new_lines)):
            if old_line != new_line:
                start_line = i
                break
        else:
            # All common lines match, check which is longer
            if len(old_lines) == len(new_lines):
                return None  # Files identical
            start_line = min(len(old_lines), len(new_lines))

        # Find last differing line (working backwards)
        end_line = max(len(old_lines), len(new_lines)) - 1

        return (start_line, end_line)
