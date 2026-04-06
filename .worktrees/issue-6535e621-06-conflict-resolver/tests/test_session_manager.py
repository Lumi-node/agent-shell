"""
Tests for SessionManager: Event Sourcing and Session State Management

Covers:
- Event recording and appending to events.log
- Session state reconstruction from snapshot + replay
- Directory tracking and working directory management
- File edit recording with SHA256 hashing
- Snapshot persistence and compression
- Crash recovery (write, snapshot, kill, restart, verify)
- Edge cases: empty session, missing snapshots, concurrent operations
"""

import pytest
import json
import time
import gzip
import tempfile
import shutil
import hashlib
import re
import os
from pathlib import Path
from unittest.mock import patch

from collab.session_manager import SessionManager
from collab.types import (
    CommandExecutedEvent,
    DirectoryChangedEvent,
    AgentRegisteredEvent,
    ApprovalQueuedEvent,
    FileEditedEvent,
    SessionState,
    CommandRecord,
    AgentInfo,
    EventReplayError,
    SnapshotCorruptedError,
)


class TestSessionManagerInit:
    """Test SessionManager initialization and directory structure."""

    def test_init_creates_session_directory(self, temp_session_dir):
        """SessionManager.__init__ creates session directory with events.log and snapshots/."""
        sm = SessionManager("test_session", temp_session_dir)

        session_path = Path(temp_session_dir) / "test_session"
        assert session_path.exists(), "Session directory should exist"
        assert (session_path / "snapshots").exists(), "snapshots/ subdirectory should exist"

    def test_init_idempotent(self, temp_session_dir):
        """Multiple SessionManager instances with same session_name work correctly."""
        sm1 = SessionManager("test_session", temp_session_dir)
        sm2 = SessionManager("test_session", temp_session_dir)

        # Both should reference same session directory
        assert sm1.session_dir == sm2.session_dir


class TestEventRecording:
    """Test event recording and log appending."""

    def test_record_event_appends_to_log(self, session_manager_fixture):
        """record_event() appends immutable event to events.log with UUID and timestamp."""
        sm = session_manager_fixture

        payload = {
            "approval_id": "approval_1",
            "agent_id": "agent_1",
            "command": "echo hello",
            "working_dir": "/tmp",
            "timestamp": time.time(),
        }
        sm.record_event("approval_queued", "agent_1", payload)

        # Verify events.log contains the event
        assert sm.events_log_path.exists(), "events.log should exist"

        with open(sm.events_log_path, "r") as f:
            lines = f.readlines()
            assert len(lines) == 1, "events.log should have 1 line"

            event_dict = json.loads(lines[0])
            assert event_dict["event_type"] == "approval_queued"
            assert "event_id" in event_dict
            assert "timestamp" in event_dict
            assert event_dict["session_id"] == sm.session_id

    def test_record_multiple_events(self, session_manager_fixture):
        """record_event() appends multiple events sequentially."""
        sm = session_manager_fixture

        for i in range(5):
            payload = {
                "approval_id": f"approval_{i}",
                "agent_id": f"agent_{i}",
                "command": f"command_{i}",
                "working_dir": "/tmp",
                "timestamp": time.time(),
            }
            sm.record_event("approval_queued", f"agent_{i}", payload)

        with open(sm.events_log_path, "r") as f:
            lines = f.readlines()
            assert len(lines) == 5, "events.log should have 5 lines"

    def test_event_has_unique_ids(self, session_manager_fixture):
        """Multiple events have unique event_ids."""
        sm = session_manager_fixture

        event_ids = []
        for i in range(3):
            sm.record_event(
                "approval_queued",
                "agent_1",
                {
                    "approval_id": f"approval_{i}",
                    "agent_id": "agent_1",
                    "command": "test",
                    "working_dir": "/tmp",
                    "timestamp": time.time(),
                },
            )

        with open(sm.events_log_path, "r") as f:
            for line in f:
                event_dict = json.loads(line)
                event_ids.append(event_dict["event_id"])

        assert len(event_ids) == len(set(event_ids)), "All event_ids should be unique"

    def test_event_timestamps_are_ordered(self, session_manager_fixture):
        """Event timestamps increase or stay same (monotonic)."""
        sm = session_manager_fixture

        for i in range(5):
            sm.record_event("approval_queued", "agent_1", {"agent_id": "agent_1"})
            time.sleep(0.001)  # Small delay to ensure order

        with open(sm.events_log_path, "r") as f:
            timestamps = []
            for line in f:
                event_dict = json.loads(line)
                timestamps.append(event_dict["timestamp"])

        # Verify monotonically increasing
        for i in range(len(timestamps) - 1):
            assert timestamps[i] <= timestamps[i + 1], "Timestamps should be monotonic"


class TestStateReconstruction:
    """Test get_session_state and event replay."""

    def test_get_session_state_empty_session(self, session_manager_fixture):
        """get_session_state() returns empty SessionState for new session."""
        sm = session_manager_fixture

        state = sm.get_session_state()
        assert state["session_id"] == sm.session_id
        assert state["agents"] == {}
        assert state["current_working_dirs"] == {}
        assert state["recent_commands"] == []
        assert state["event_count"] == 0

    def test_get_session_state_with_agent_registered(self, session_manager_fixture):
        """get_session_state() reflects AgentRegisteredEvent."""
        sm = session_manager_fixture

        payload = {
            "agent_id": "agent_1",
            "capabilities": ["python_testing"],
            "metadata": {"version": "1.0"},
            "timestamp": time.time(),
        }
        sm.record_event("agent_registered", "agent_1", payload)

        state = sm.get_session_state()
        assert "agent_1" in state["agents"]
        assert state["agents"]["agent_1"]["capabilities"] == ["python_testing"]
        assert state["event_count"] == 1

    def test_get_session_state_with_commands(self, session_manager_fixture):
        """get_session_state() reflects CommandExecutedEvent."""
        sm = session_manager_fixture

        payload = {
            "approval_id": "approval_1",
            "agent_id": "agent_1",
            "command": "echo hello",
            "exit_code": 0,
            "output": "hello",
            "working_dir": "/tmp",
            "timestamp": time.time(),
            "duration_ms": 100,
        }
        sm.record_event("command_executed", "agent_1", payload)

        state = sm.get_session_state()
        assert len(state["recent_commands"]) == 1
        assert state["recent_commands"][0]["command"] == "echo hello"
        assert state["current_working_dirs"]["agent_1"] == "/tmp"

    def test_recent_commands_limited_to_100(self, session_manager_fixture):
        """get_session_state() keeps only last 100 commands."""
        sm = session_manager_fixture

        # Add 150 commands
        for i in range(150):
            payload = {
                "approval_id": f"approval_{i}",
                "agent_id": "agent_1",
                "command": f"cmd_{i}",
                "exit_code": 0,
                "output": "",
                "working_dir": "/tmp",
                "timestamp": time.time() + i,
                "duration_ms": 10,
            }
            sm.record_event("command_executed", "agent_1", payload)

        state = sm.get_session_state()
        assert len(state["recent_commands"]) == 100, "Should keep last 100 commands"
        # Verify we have the last 50 commands (150 - 100 = 50)
        assert state["recent_commands"][0]["command"] == "cmd_50"
        assert state["recent_commands"][-1]["command"] == "cmd_149"


class TestDirectoryTracking:
    """Test set_cwd, get_cwd, and DirectoryChangedEvent handling."""

    def test_set_cwd_records_directory_changed_event(self, session_manager_fixture):
        """set_cwd() records DirectoryChangedEvent."""
        sm = session_manager_fixture

        sm.set_cwd("agent_1", "/home/user")

        with open(sm.events_log_path, "r") as f:
            lines = f.readlines()
            assert len(lines) == 1

            event_dict = json.loads(lines[0])
            assert event_dict["event_type"] == "directory_changed"
            assert event_dict["payload"]["agent_id"] == "agent_1"
            assert event_dict["payload"]["new_cwd"] == "/home/user"

    def test_get_cwd_returns_tracked_directory(self, session_manager_fixture):
        """get_cwd() returns current working directory for agent."""
        sm = session_manager_fixture

        sm.set_cwd("agent_1", "/home/user")
        cwd = sm.get_cwd("agent_1")

        assert cwd == "/home/user"

    def test_get_cwd_default_agent(self, session_manager_fixture):
        """get_cwd(None) returns first agent's directory."""
        sm = session_manager_fixture

        sm.set_cwd("agent_1", "/home/user")
        sm.set_cwd("agent_2", "/var/log")

        cwd = sm.get_cwd()
        assert cwd in ["/home/user", "/var/log"], "Should return one of the agent directories"

    def test_concurrent_directory_changes(self, session_manager_fixture):
        """Multiple agents with different working directories tracked separately."""
        sm = session_manager_fixture

        sm.set_cwd("agent_1", "/tmp")
        sm.set_cwd("agent_2", "/var")
        sm.set_cwd("agent_3", "/home")

        state = sm.get_session_state()
        assert state["current_working_dirs"]["agent_1"] == "/tmp"
        assert state["current_working_dirs"]["agent_2"] == "/var"
        assert state["current_working_dirs"]["agent_3"] == "/home"


class TestRecentCommands:
    """Test get_recent_commands() with limit parameter."""

    def test_get_recent_commands_respects_limit(self, session_manager_fixture):
        """get_recent_commands(limit) respects limit parameter."""
        sm = session_manager_fixture

        # Add 20 commands
        for i in range(20):
            payload = {
                "approval_id": f"approval_{i}",
                "agent_id": "agent_1",
                "command": f"cmd_{i}",
                "exit_code": 0,
                "output": "",
                "working_dir": "/tmp",
                "timestamp": time.time() + i,
                "duration_ms": 10,
            }
            sm.record_event("command_executed", "agent_1", payload)

        commands = sm.get_recent_commands(limit=5)
        assert len(commands) == 5, "Should return only 5 commands"
        # Should be most recent (indices 15-19)
        assert commands[0]["command"] == "cmd_15"
        assert commands[-1]["command"] == "cmd_19"

    def test_get_recent_commands_default_limit(self, session_manager_fixture):
        """get_recent_commands() defaults to 10."""
        sm = session_manager_fixture

        for i in range(20):
            payload = {
                "approval_id": f"approval_{i}",
                "agent_id": "agent_1",
                "command": f"cmd_{i}",
                "exit_code": 0,
                "output": "",
                "working_dir": "/tmp",
                "timestamp": time.time() + i,
                "duration_ms": 10,
            }
            sm.record_event("command_executed", "agent_1", payload)

        commands = sm.get_recent_commands()
        assert len(commands) == 10, "Default limit should be 10"


class TestListAgents:
    """Test list_agents() method."""

    def test_list_agents_empty(self, session_manager_fixture):
        """list_agents() returns empty dict for new session."""
        sm = session_manager_fixture

        agents = sm.list_agents()
        assert agents == {}

    def test_list_agents_returns_registered_agents(self, session_manager_fixture):
        """list_agents() returns all registered agents."""
        sm = session_manager_fixture

        for i in range(3):
            payload = {
                "agent_id": f"agent_{i}",
                "capabilities": ["python_testing"],
                "metadata": {},
                "timestamp": time.time(),
            }
            sm.record_event("agent_registered", f"agent_{i}", payload)

        agents = sm.list_agents()
        assert len(agents) == 3
        assert "agent_0" in agents
        assert "agent_1" in agents
        assert "agent_2" in agents


class TestFileEditing:
    """Test record_file_edit() with SHA256 hashing and line ranges."""

    def test_record_file_edit_computes_hashes(self, session_manager_fixture):
        """record_file_edit() computes SHA256 hashes."""
        sm = session_manager_fixture

        old_content = "line1\nline2\nline3\n"
        new_content = "line1\nmodified\nline3\n"

        sm.record_file_edit("/tmp/test.txt", "agent_1", old_content, new_content)

        with open(sm.events_log_path, "r") as f:
            event_dict = json.loads(f.readline())
            payload = event_dict["payload"]

            old_hash = hashlib.sha256(old_content.encode("utf-8")).hexdigest()
            new_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

            assert payload["old_content_hash"] == old_hash
            assert payload["new_content_hash"] == new_hash

    def test_record_file_edit_line_range(self, session_manager_fixture):
        """record_file_edit() calculates line range for the edit."""
        sm = session_manager_fixture

        old_content = "line1\nline2\nline3\n"
        new_content = "line1\nmodified\nline3\n"

        sm.record_file_edit("/tmp/test.txt", "agent_1", old_content, new_content)

        with open(sm.events_log_path, "r") as f:
            event_dict = json.loads(f.readline())
            payload = event_dict["payload"]

            # Line 1 (index 1) was modified
            assert payload["line_range"] is not None
            assert payload["line_range"][0] == 1


class TestSnapshotPersistence:
    """Test persist_snapshot() and snapshot file format."""

    def test_persist_snapshot_creates_file(self, session_manager_fixture):
        """persist_snapshot() creates snapshot file in snapshots/ directory."""
        sm = session_manager_fixture

        # Add some events
        for i in range(5):
            payload = {
                "approval_id": f"approval_{i}",
                "agent_id": f"agent_{i}",
                "command": f"cmd_{i}",
                "working_dir": "/tmp",
                "timestamp": time.time(),
            }
            sm.record_event("approval_queued", f"agent_{i}", payload)

        sm.persist_snapshot()

        # Verify snapshot file exists
        snapshot_files = list(sm.snapshots_dir.glob("snapshot-*.bin"))
        assert len(snapshot_files) == 1, "Should have created one snapshot"

    def test_snapshot_filename_format(self, session_manager_fixture):
        r"""Snapshot filename matches regex r'snapshot-([\d.]+)\.bin' with full-precision timestamp."""
        sm = session_manager_fixture

        sm.persist_snapshot()

        snapshot_files = list(sm.snapshots_dir.glob("snapshot-*.bin"))
        assert len(snapshot_files) == 1

        filename = snapshot_files[0].name
        match = re.match(r"snapshot-([\d.]+)\.bin", filename)
        assert match is not None, f"Filename {filename} should match regex"

        # Verify timestamp is a valid float
        timestamp_str = match.group(1)
        timestamp = float(timestamp_str)
        assert timestamp > 0, "Timestamp should be positive"

    def test_snapshot_is_gzip_compressed(self, session_manager_fixture):
        """Snapshot file is gzip-compressed."""
        sm = session_manager_fixture

        # Add event and snapshot
        sm.record_event(
            "approval_queued",
            "agent_1",
            {
                "approval_id": "approval_1",
                "agent_id": "agent_1",
                "command": "test",
                "working_dir": "/tmp",
                "timestamp": time.time(),
            },
        )
        sm.persist_snapshot()

        snapshot_file = list(sm.snapshots_dir.glob("snapshot-*.bin"))[0]

        # Verify it's gzip (should be readable with gzip)
        with gzip.open(snapshot_file, "rb") as f:
            content = f.read()
            # Should be valid JSON
            data = json.loads(content.decode("utf-8"))
            assert "session_id" in data

    def test_snapshot_contains_state(self, session_manager_fixture):
        """Snapshot contains complete session state."""
        sm = session_manager_fixture

        # Add agent and command
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["testing"],
                "metadata": {},
                "timestamp": time.time(),
            },
        )
        sm.record_event(
            "command_executed",
            "agent_1",
            {
                "approval_id": "approval_1",
                "agent_id": "agent_1",
                "command": "echo test",
                "exit_code": 0,
                "output": "test",
                "working_dir": "/tmp",
                "timestamp": time.time(),
                "duration_ms": 100,
            },
        )

        sm.persist_snapshot()

        # Load snapshot and verify content
        snapshot_file = list(sm.snapshots_dir.glob("snapshot-*.bin"))[0]
        with gzip.open(snapshot_file, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))

        assert "agent_1" in data["agents"]
        assert len(data["recent_commands"]) == 1

    def test_snapshot_compression_size(self, session_manager_fixture):
        """Snapshot file size < events.log size for 100+ events."""
        sm = session_manager_fixture

        # Add 101 events
        for i in range(101):
            sm.record_event(
                "command_executed",
                "agent_1",
                {
                    "approval_id": f"approval_{i}",
                    "agent_id": "agent_1",
                    "command": f"echo test_{i}",
                    "exit_code": 0,
                    "output": f"test_{i}",
                    "working_dir": "/tmp",
                    "timestamp": time.time() + i,
                    "duration_ms": 100,
                },
            )

        sm.persist_snapshot()

        events_log_size = sm.events_log_path.stat().st_size
        snapshot_file = list(sm.snapshots_dir.glob("snapshot-*.bin"))[0]
        snapshot_size = snapshot_file.stat().st_size

        assert snapshot_size < events_log_size, "Snapshot should be smaller than event log"


class TestSnapshotReplay:
    """Test replay_from_snapshot() and event replay accuracy."""

    def test_replay_from_snapshot_loads_state(self, session_manager_fixture):
        """replay_from_snapshot() loads and replays state."""
        sm = session_manager_fixture

        # Add agent
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["testing"],
                "metadata": {},
                "timestamp": time.time(),
            },
        )

        # Create snapshot
        sm.persist_snapshot()
        snapshot_ts = sm.get_session_state()["last_updated_at"]

        # Add more events
        sm.record_event(
            "command_executed",
            "agent_1",
            {
                "approval_id": "approval_1",
                "agent_id": "agent_1",
                "command": "echo test",
                "exit_code": 0,
                "output": "test",
                "working_dir": "/tmp",
                "timestamp": time.time(),
                "duration_ms": 100,
            },
        )

        # Replay from snapshot
        replayed_state = sm.replay_from_snapshot(snapshot_ts)

        assert "agent_1" in replayed_state["agents"]
        assert len(replayed_state["recent_commands"]) == 1

    def test_replay_accuracy_matches_full_replay(self, session_manager_fixture):
        """replay_from_snapshot() produces identical state to full replay after snapshot."""
        sm = session_manager_fixture

        # Add initial events with increasing timestamps
        base_time = time.time()
        for i in range(5):
            sm.record_event(
                "command_executed",
                "agent_1",
                {
                    "approval_id": f"approval_{i}",
                    "agent_id": "agent_1",
                    "command": f"cmd_{i}",
                    "exit_code": 0,
                    "output": "",
                    "working_dir": "/tmp",
                    "timestamp": base_time + i,
                    "duration_ms": 10,
                },
            )

        # Get state and create snapshot
        sm._state = None  # Clear cache to force reload
        state_before_snapshot = sm.get_session_state()
        commands_before = len(state_before_snapshot["recent_commands"])

        # Snapshot and get snapshot timestamp
        sm.persist_snapshot()
        snapshot_ts = state_before_snapshot["last_updated_at"]

        # Add more events with later timestamps (strictly after snapshot)
        for i in range(5, 10):
            sm.record_event(
                "command_executed",
                "agent_1",
                {
                    "approval_id": f"approval_{i}",
                    "agent_id": "agent_1",
                    "command": f"cmd_{i}",
                    "exit_code": 0,
                    "output": "",
                    "working_dir": "/tmp",
                    "timestamp": base_time + 100 + i,  # Much later to ensure > snapshot_ts
                    "duration_ms": 10,
                },
            )

        # Get full state (should have 10 commands)
        sm._state = None  # Clear cache
        full_state = sm.get_session_state()

        # Replay from snapshot (should have 5 from snapshot + 5 after = 10 total)
        replayed_state = sm.replay_from_snapshot(snapshot_ts)

        # Both should have same number of commands
        assert len(full_state["recent_commands"]) == 10
        assert len(replayed_state["recent_commands"]) == 10

        # Verify commands are identical
        for i, cmd in enumerate(replayed_state["recent_commands"]):
            assert cmd["command"] == full_state["recent_commands"][i]["command"]


class TestCrashRecovery:
    """Test crash recovery: write events, snapshot, restart, verify state."""

    def test_crash_recovery_scenario(self):
        """Crash recovery test: write 50 events, snapshot, restart, verify."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Phase 1: Write events and snapshot
            sm1 = SessionManager("recovery_test", temp_dir)

            agent_id = "agent_1"
            base_time = time.time()

            # Add 50 command events
            for i in range(50):
                payload = {
                    "approval_id": f"approval_{i}",
                    "agent_id": agent_id,
                    "command": f"echo cmd_{i}",
                    "exit_code": 0,
                    "output": f"output_{i}",
                    "working_dir": "/tmp",
                    "timestamp": base_time + i * 0.001,
                    "duration_ms": 100,
                }
                sm1.record_event("command_executed", agent_id, payload)

            # Get state before snapshot (clear cache to force reload)
            sm1._state = None
            state1 = sm1.get_session_state()
            command_count_before = len(state1["recent_commands"])
            event_count_before = state1["event_count"]

            # Create snapshot
            sm1.persist_snapshot()

            # Phase 2: Restart (simulate crash) - create new instance
            # Don't clear the old one's cache, create completely fresh instance
            sm2 = SessionManager("recovery_test", temp_dir)

            # Verify state recovered
            state2 = sm2.get_session_state()

            assert state2["event_count"] == event_count_before, "Event count should be preserved"
            assert (
                len(state2["recent_commands"]) == command_count_before
            ), "Commands should be preserved"
            assert state2["recent_commands"][-1]["command"] == f"echo cmd_49"

    def test_recovery_without_snapshot(self):
        """Recovery from events.log when no snapshot exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Write events
            sm1 = SessionManager("no_snapshot_test", temp_dir)

            for i in range(10):
                sm1.record_event(
                    "command_executed",
                    "agent_1",
                    {
                        "approval_id": f"approval_{i}",
                        "agent_id": "agent_1",
                        "command": f"cmd_{i}",
                        "exit_code": 0,
                        "output": "",
                        "working_dir": "/tmp",
                        "timestamp": time.time() + i,
                        "duration_ms": 10,
                    },
                )

            state1 = sm1.get_session_state()

            # Restart without snapshot
            sm2 = SessionManager("no_snapshot_test", temp_dir)
            state2 = sm2.get_session_state()

            assert state2["event_count"] == state1["event_count"]
            assert len(state2["recent_commands"]) == len(state1["recent_commands"])


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_session(self, session_manager_fixture):
        """Empty session has correct initial state."""
        sm = session_manager_fixture

        state = sm.get_session_state()
        assert state["agents"] == {}
        assert state["recent_commands"] == []
        assert state["event_count"] == 0

    def test_missing_events_log(self):
        """SessionManager works correctly when events.log doesn't exist yet."""
        with tempfile.TemporaryDirectory() as temp_dir:
            sm = SessionManager("test", temp_dir)

            # Should not error
            state = sm.get_session_state()
            assert state["event_count"] == 0

    def test_multiple_snapshots(self, session_manager_fixture):
        """Multiple snapshots are created and managed correctly."""
        sm = session_manager_fixture

        timestamps = []
        for batch in range(3):
            for i in range(5):
                sm.record_event(
                    "approval_queued",
                    "agent_1",
                    {
                        "approval_id": f"approval_{batch}_{i}",
                        "agent_id": "agent_1",
                        "command": "test",
                        "working_dir": "/tmp",
                        "timestamp": time.time(),
                    },
                )

            sm.persist_snapshot()
            timestamps.append(time.time())
            time.sleep(0.01)

        snapshot_files = list(sm.snapshots_dir.glob("snapshot-*.bin"))
        assert len(snapshot_files) >= 2, "Should have created multiple snapshots"

    def test_concurrent_agent_directory_changes(self, session_manager_fixture):
        """Multiple agents changing directories concurrently."""
        sm = session_manager_fixture

        for i in range(3):
            sm.set_cwd(f"agent_{i}", f"/path/{i}")

        state = sm.get_session_state()
        for i in range(3):
            assert state["current_working_dirs"][f"agent_{i}"] == f"/path/{i}"

    def test_state_cache_invalidation(self, session_manager_fixture):
        """State cache is invalidated after record_event()."""
        sm = session_manager_fixture

        state1 = sm.get_session_state()
        sm.record_event(
            "approval_queued",
            "agent_1",
            {
                "approval_id": "approval_1",
                "agent_id": "agent_1",
                "command": "test",
                "working_dir": "/tmp",
                "timestamp": time.time(),
            },
        )

        # Force fresh state (should not use cache)
        state2 = sm.get_session_state()

        assert state2["event_count"] == 1
        assert state1["event_count"] == 0


class TestEventTypes:
    """Test handling of different event types during replay."""

    def test_replay_approval_queued_event(self, session_manager_fixture):
        """ApprovalQueuedEvent creates pending approval in state."""
        sm = session_manager_fixture

        sm.record_event(
            "approval_queued",
            "agent_1",
            {
                "approval_id": "approval_1",
                "agent_id": "agent_1",
                "command": "echo test",
                "working_dir": "/tmp",
                "timestamp": time.time(),
            },
        )

        state = sm.get_session_state()
        assert "approval_1" in state["pending_approvals"]
        assert state["pending_approvals"]["approval_1"]["status"] == "pending"

    def test_replay_approval_decided_event(self, session_manager_fixture):
        """ApprovalDecidedEvent updates approval status."""
        sm = session_manager_fixture

        sm.record_event(
            "approval_queued",
            "agent_1",
            {
                "approval_id": "approval_1",
                "agent_id": "agent_1",
                "command": "echo test",
                "working_dir": "/tmp",
                "timestamp": time.time(),
            },
        )

        sm.record_event(
            "approval_decided",
            "agent_1",
            {
                "approval_id": "approval_1",
                "status": "approved",
                "decided_at": time.time(),
                "edited_command": None,
                "decision_note": None,
            },
        )

        state = sm.get_session_state()
        assert state["pending_approvals"]["approval_1"]["status"] == "approved"
        assert state["pending_approvals"]["approval_1"]["decided_at"] is not None


class TestTimestampPrecision:
    """Test idempotent replay with full-precision timestamps."""

    def test_replay_from_snapshot_with_full_precision(self, session_manager_fixture):
        """replay_from_snapshot() works correctly with full-precision timestamps."""
        sm = session_manager_fixture

        # Add agent event
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["testing"],
                "metadata": {},
                "timestamp": time.time(),
            },
        )

        # Create snapshot and capture exact timestamp
        sm.persist_snapshot()
        snapshot_ts = sm.get_session_state()["last_updated_at"]

        # Add another event after the snapshot
        time.sleep(0.01)
        sm.record_event(
            "command_executed",
            "agent_1",
            {
                "approval_id": "approval_1",
                "agent_id": "agent_1",
                "command": "echo test",
                "exit_code": 0,
                "output": "test",
                "working_dir": "/tmp",
                "timestamp": time.time(),
                "duration_ms": 100,
            },
        )

        # Replay from snapshot using exact full-precision timestamp
        replayed_state = sm.replay_from_snapshot(snapshot_ts)

        # Verify snapshot loaded successfully
        assert "agent_1" in replayed_state["agents"]
        assert len(replayed_state["recent_commands"]) == 1

    def test_replay_from_snapshot_idempotent_with_same_millisecond_events(
        self, session_manager_fixture
    ):
        """
        replay_from_snapshot() handles events after snapshot correctly.

        Ensures that events strictly after the snapshot timestamp are included
        in replay, while snapshot includes all events up to and including the
        snapshot timestamp.
        """
        sm = session_manager_fixture

        # Add first event
        base_time = time.time()
        sm.record_event(
            "command_executed",
            "agent_1",
            {
                "approval_id": "approval_1",
                "agent_id": "agent_1",
                "command": "cmd_1",
                "exit_code": 0,
                "output": "output_1",
                "working_dir": "/tmp",
                "timestamp": base_time,
                "duration_ms": 10,
            },
        )

        # Snapshot - captures cmd_1
        sm.persist_snapshot()
        snapshot_ts = sm.get_session_state()["last_updated_at"]

        # Add two more events strictly after snapshot timestamp
        # to test handling of events after snapshot boundary
        sm.record_event(
            "command_executed",
            "agent_1",
            {
                "approval_id": "approval_2",
                "agent_id": "agent_1",
                "command": "cmd_2",
                "exit_code": 0,
                "output": "output_2",
                "working_dir": "/tmp",
                "timestamp": snapshot_ts + 0.001,  # After snapshot
                "duration_ms": 10,
            },
        )

        sm.record_event(
            "command_executed",
            "agent_1",
            {
                "approval_id": "approval_3",
                "agent_id": "agent_1",
                "command": "cmd_3",
                "exit_code": 0,
                "output": "output_3",
                "working_dir": "/tmp",
                "timestamp": snapshot_ts + 0.002,
                "duration_ms": 10,
            },
        )

        # Replay from snapshot
        replayed_state = sm.replay_from_snapshot(snapshot_ts)

        # Should have exactly 3 commands total (cmd_1 from snapshot + cmd_2, cmd_3 after)
        assert len(replayed_state["recent_commands"]) == 3
        assert replayed_state["recent_commands"][0]["command"] == "cmd_1"
        assert replayed_state["recent_commands"][1]["command"] == "cmd_2"
        assert replayed_state["recent_commands"][2]["command"] == "cmd_3"

    def test_snapshot_file_contains_full_precision_timestamp(
        self, session_manager_fixture
    ):
        """Snapshot filename contains full-precision timestamp matching state."""
        sm = session_manager_fixture

        # Add an event
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["testing"],
                "metadata": {},
                "timestamp": time.time(),
            },
        )

        # Create snapshot
        sm.persist_snapshot()
        state = sm.get_session_state()

        # Get the snapshot filename
        snapshot_files = list(sm.snapshots_dir.glob("snapshot-*.bin"))
        assert len(snapshot_files) == 1

        filename = snapshot_files[0].name
        match = re.match(r"snapshot-([\d.]+)\.bin", filename)
        assert match is not None

        # Extract timestamp from filename and verify it matches state timestamp
        timestamp_from_filename = float(match.group(1))
        state_timestamp = state["last_updated_at"]

        # Should match exactly (or be very close due to float precision)
        assert (
            abs(timestamp_from_filename - state_timestamp) < 1e-9
        ), f"Filename timestamp {timestamp_from_filename} should match state timestamp {state_timestamp}"
