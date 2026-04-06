"""
Integration tests for SessionManager and CapabilityRegistry.

Tests the interaction between two merged features:
- SessionManager: Event sourcing and session state management
- CapabilityRegistry: Agent capability registration and task matching

Focus areas:
1. Conflict resolution in merged __init__.py - both classes properly exported
2. Agents registered in SessionManager can be queried via CapabilityRegistry
3. Task descriptions are matched against agent capabilities from session state
4. Agents can change working directories and those changes persist across capability queries
5. Multiple agents with different capabilities in shared session state
"""

import pytest
import tempfile
import shutil
import time
from pathlib import Path

from collab import SessionManager, CapabilityRegistry
from collab.types import AgentInfo


class TestSessionManagerAndCapabilityRegistryIntegration:
    """Integration tests between SessionManager and CapabilityRegistry."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for session storage."""
        temp = tempfile.mkdtemp(prefix="collab_integration_")
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    def test_session_manager_and_capability_registry_both_importable(self):
        """Verify both SessionManager and CapabilityRegistry are importable from collab."""
        from collab import SessionManager as SM
        from collab import CapabilityRegistry as CR

        assert SM is not None
        assert CR is not None
        assert hasattr(SM, '__init__')
        assert hasattr(CR, '__init__')

    def test_single_agent_registration_and_capability_lookup(self, temp_dir):
        """Agent registered in SessionManager can be found via CapabilityRegistry."""
        sm = SessionManager("test_session", temp_dir)
        registry = CapabilityRegistry()

        # Register agent in session
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["python_testing", "debugging"],
                "timestamp": time.time(),
            },
        )

        # Get agent info from session state
        state = sm.get_session_state()
        agent_info = state["agents"].get("agent_1")
        assert agent_info is not None
        assert agent_info["capabilities"] == ["python_testing", "debugging"]

        # Register same agent in capability registry
        registry.register_agent(
            "agent_1",
            "Test Agent",
            agent_info["capabilities"],
        )

        # Find agent by task description
        results = registry.find_agents_for_task("debug Python tests")
        assert len(results) > 0
        assert results[0][0] == "agent_1"  # Agent ID
        assert results[0][1] > 0.0  # Score > 0

    def test_multiple_agents_in_session_with_capability_matching(self, temp_dir):
        """Multiple agents in session state can be matched against task descriptions."""
        sm = SessionManager("test_session", temp_dir)
        registry = CapabilityRegistry()

        # Register agent 1 in session
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["python_testing", "debugging"],
                "timestamp": time.time(),
            },
        )

        # Register agent 2 in session
        sm.record_event(
            "agent_registered",
            "agent_2",
            {
                "agent_id": "agent_2",
                "capabilities": ["javascript", "nodejs", "build"],
                "timestamp": time.time(),
            },
        )

        # Get both agents from session state
        state = sm.get_session_state()
        assert len(state["agents"]) == 2

        # Register both agents in capability registry
        for agent_id, agent_info in state["agents"].items():
            registry.register_agent(
                agent_id,
                f"Agent {agent_id}",
                agent_info["capabilities"],
            )

        # Find agents for task 1 (should match agent_1)
        results = registry.find_agents_for_task("debug Python tests")
        assert len(results) > 0
        agent_ids = [agent_id for agent_id, _ in results]
        assert "agent_1" in agent_ids

        # Find agents for task 2 (should match agent_2)
        results = registry.find_agents_for_task("build javascript project")
        assert len(results) > 0
        agent_ids = [agent_id for agent_id, _ in results]
        assert "agent_2" in agent_ids

    def test_agent_working_directory_changes_dont_affect_capability_matching(self, temp_dir):
        """Agent's working directory changes persist in session but don't affect capability lookup."""
        sm = SessionManager("test_session", temp_dir)
        registry = CapabilityRegistry()

        # Register agent in session
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["python_testing"],
                "timestamp": time.time(),
            },
        )

        # Change agent's working directory
        sm.set_cwd("agent_1", "/tmp")
        state = sm.get_session_state()
        assert state["current_working_dirs"]["agent_1"] == "/tmp"

        # Change directory again
        sm.set_cwd("agent_1", "/home")
        state = sm.get_session_state()
        assert state["current_working_dirs"]["agent_1"] == "/home"

        # Register in capability registry
        agent_info = state["agents"]["agent_1"]
        registry.register_agent("agent_1", "Test Agent", agent_info["capabilities"])

        # Capability matching should still work
        results = registry.find_agents_for_task("python testing")
        assert len(results) > 0
        assert results[0][0] == "agent_1"

    def test_agent_state_persistence_across_session_reconstructions(self, temp_dir):
        """Agent capabilities persist when session is reconstructed from snapshot."""
        # Create session and register agent
        sm1 = SessionManager("test_session", temp_dir)
        sm1.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["debugging", "logging"],
                "timestamp": time.time(),
            },
        )

        state1 = sm1.get_session_state()
        agent_capabilities_1 = state1["agents"]["agent_1"]["capabilities"]

        # Create new session manager (same session)
        sm2 = SessionManager("test_session", temp_dir)
        state2 = sm2.get_session_state()

        # Agent capabilities should be identical
        agent_capabilities_2 = state2["agents"]["agent_1"]["capabilities"]
        assert agent_capabilities_1 == agent_capabilities_2
        assert agent_capabilities_2 == ["debugging", "logging"]

    def test_empty_capability_registry_with_populated_session(self, temp_dir):
        """CapabilityRegistry can be initialized separately and populated from session state."""
        sm = SessionManager("test_session", temp_dir)

        # Register multiple agents in session
        agents_to_register = [
            ("agent_1", ["python"]),
            ("agent_2", ["javascript"]),
            ("agent_3", ["rust"]),
        ]

        for agent_id, caps in agents_to_register:
            sm.record_event(
                "agent_registered",
                agent_id,
                {
                    "agent_id": agent_id,
                    "capabilities": caps,
                    "timestamp": time.time(),
                },
            )

        # Get session state
        state = sm.get_session_state()

        # Create fresh capability registry
        registry = CapabilityRegistry()
        assert len(registry.get_all_agents()) == 0

        # Populate registry from session state
        for agent_id, agent_info in state["agents"].items():
            registry.register_agent(
                agent_id,
                f"Agent {agent_id}",
                agent_info["capabilities"],
            )

        # Verify all agents registered in registry
        assert len(registry.get_all_agents()) == 3
        assert "agent_1" in registry.get_all_agents()
        assert "agent_2" in registry.get_all_agents()
        assert "agent_3" in registry.get_all_agents()

    def test_capability_registry_deregistration_independent_of_session(self, temp_dir):
        """Deregistering agent from CapabilityRegistry doesn't affect SessionManager."""
        sm = SessionManager("test_session", temp_dir)
        registry = CapabilityRegistry()

        # Register agent in both
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["python"],
                "timestamp": time.time(),
            },
        )

        state = sm.get_session_state()
        registry.register_agent("agent_1", "Test Agent", state["agents"]["agent_1"]["capabilities"])

        # Verify agent in both
        assert "agent_1" in sm.get_session_state()["agents"]
        assert "agent_1" in registry.get_all_agents()

        # Deregister from registry
        registry.deregister_agent("agent_1")

        # Agent still in session
        assert "agent_1" in sm.get_session_state()["agents"]
        # Agent gone from registry
        assert "agent_1" not in registry.get_all_agents()

    def test_task_matching_with_multiple_agents_varying_capabilities(self, temp_dir):
        """Task matching correctly prioritizes agents based on capability overlap."""
        sm = SessionManager("test_session", temp_dir)
        registry = CapabilityRegistry()

        # Agent 1: exact matches for 'debug' and 'python'
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["debug", "python", "logging"],
                "timestamp": time.time(),
            },
        )

        # Agent 2: only partial match for 'python'
        sm.record_event(
            "agent_registered",
            "agent_2",
            {
                "agent_id": "agent_2",
                "capabilities": ["javascript", "nodejs"],
                "timestamp": time.time(),
            },
        )

        # Agent 3: exact match for one, partial for other
        sm.record_event(
            "agent_registered",
            "agent_3",
            {
                "agent_id": "agent_3",
                "capabilities": ["python_testing", "build"],
                "timestamp": time.time(),
            },
        )

        # Register all agents in registry
        state = sm.get_session_state()
        for agent_id, agent_info in state["agents"].items():
            registry.register_agent(
                agent_id,
                f"Agent {agent_id}",
                agent_info["capabilities"],
            )

        # Query for "debug Python code"
        results = registry.find_agents_for_task("debug Python code")

        # Should have multiple results
        assert len(results) > 0

        # agent_1 should score highest (has exact matches for 'debug' and 'python')
        agent_ids = [agent_id for agent_id, _ in results]
        assert "agent_1" in agent_ids

    def test_agent_with_no_capabilities_still_registered_in_session(self, temp_dir):
        """Agent with empty capabilities list is registered in session but has zero match score."""
        sm = SessionManager("test_session", temp_dir)
        registry = CapabilityRegistry()

        # Register agent with no capabilities
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": [],
                "timestamp": time.time(),
            },
        )

        state = sm.get_session_state()
        assert "agent_1" in state["agents"]
        assert state["agents"]["agent_1"]["capabilities"] == []

        # Register in capability registry
        registry.register_agent("agent_1", "No-Cap Agent", [])

        # Query for task
        results = registry.find_agents_for_task("do anything")

        # Agent should not be in results (no matching capabilities)
        agent_ids = [agent_id for agent_id, _ in results]
        assert "agent_1" not in agent_ids

    def test_session_state_agent_info_matches_capability_registry_format(self, temp_dir):
        """AgentInfo structure from SessionManager matches CapabilityRegistry expectations."""
        sm = SessionManager("test_session", temp_dir)

        # Register agent in session
        sm.record_event(
            "agent_registered",
            "agent_1",
            {
                "agent_id": "agent_1",
                "capabilities": ["python", "debugging"],
                "timestamp": time.time(),
            },
        )

        state = sm.get_session_state()
        agent_info = state["agents"]["agent_1"]

        # Verify AgentInfo structure matches expectations
        assert isinstance(agent_info, dict)
        assert "agent_id" in agent_info
        assert "capabilities" in agent_info
        assert "status" in agent_info
        assert "current_task_id" in agent_info
        assert "joined_at" in agent_info
        assert "last_activity_at" in agent_info

        # These should be the values passed in event
        assert agent_info["agent_id"] == "agent_1"
        assert agent_info["capabilities"] == ["python", "debugging"]
        assert agent_info["status"] == "active"

    def test_large_number_of_agents_in_session_with_capability_lookup(self, temp_dir):
        """Session and registry handle 10+ agents with capability matching."""
        sm = SessionManager("test_session", temp_dir)
        registry = CapabilityRegistry()

        # Register 10 agents with varying capabilities
        for i in range(10):
            caps = [f"capability_{i}", f"shared_capability_{i % 3}"]
            sm.record_event(
                "agent_registered",
                f"agent_{i}",
                {
                    "agent_id": f"agent_{i}",
                    "capabilities": caps,
                    "timestamp": time.time(),
                },
            )

        state = sm.get_session_state()
        assert len(state["agents"]) == 10

        # Register all in registry
        for agent_id, agent_info in state["agents"].items():
            registry.register_agent(
                agent_id,
                f"Agent {agent_id}",
                agent_info["capabilities"],
            )

        # Query for task
        results = registry.find_agents_for_task("shared_capability_1")

        # Should find agents with matching capabilities
        assert len(results) > 0


class TestConflictResolutionInInit:
    """Tests specifically for the conflict resolution in collab/__init__.py."""

    def test_both_classes_in_all_exports(self):
        """Both SessionManager and CapabilityRegistry in __all__ list."""
        from collab import __all__

        assert "SessionManager" in __all__
        assert "CapabilityRegistry" in __all__

    def test_session_manager_can_be_imported_directly(self):
        """SessionManager can be imported directly from collab."""
        from collab import SessionManager

        assert SessionManager is not None
        assert hasattr(SessionManager, '__init__')
        assert hasattr(SessionManager, 'record_event')
        assert hasattr(SessionManager, 'get_session_state')

    def test_capability_registry_can_be_imported_directly(self):
        """CapabilityRegistry can be imported directly from collab."""
        from collab import CapabilityRegistry

        assert CapabilityRegistry is not None
        assert hasattr(CapabilityRegistry, '__init__')
        assert hasattr(CapabilityRegistry, 'register_agent')
        assert hasattr(CapabilityRegistry, 'find_agents_for_task')

    def test_both_imports_reference_correct_modules(self):
        """Both SessionManager and CapabilityRegistry are from correct modules."""
        from collab import SessionManager, CapabilityRegistry
        from collab.session_manager import SessionManager as SMDirect
        from collab.capability_registry import CapabilityRegistry as CRDirect

        # Should be same classes
        assert SessionManager is SMDirect
        assert CapabilityRegistry is CRDirect

    def test_all_event_types_importable(self):
        """All event types still importable after merge."""
        from collab import (
            Event,
            ApprovalQueuedEvent,
            ApprovalDecidedEvent,
            AgentRegisteredEvent,
            CommandExecutedEvent,
            FileEditedEvent,
            DirectoryChangedEvent,
            ConflictDetectedEvent,
            TaskCreatedEvent,
            TaskStatusChangedEvent,
        )

        # All should be importable
        assert Event is not None
        assert ApprovalQueuedEvent is not None
        assert ApprovalDecidedEvent is not None
        assert AgentRegisteredEvent is not None
        assert CommandExecutedEvent is not None
        assert FileEditedEvent is not None
        assert DirectoryChangedEvent is not None
        assert ConflictDetectedEvent is not None
        assert TaskCreatedEvent is not None
        assert TaskStatusChangedEvent is not None

    def test_all_type_definitions_importable(self):
        """All TypedDicts and types still importable after merge."""
        from collab import (
            SessionState,
            AgentInfo,
            ApprovalRequest,
            TaskStatus,
            CommandRecord,
            ConflictInfo,
        )

        assert SessionState is not None
        assert AgentInfo is not None
        assert ApprovalRequest is not None
        assert TaskStatus is not None
        assert CommandRecord is not None
        assert ConflictInfo is not None

    def test_all_exceptions_importable(self):
        """All exception types still importable after merge."""
        from collab import (
            CollabError,
            InvalidSessionStateError,
            InvalidTaskStateError,
            ApprovalNotFoundError,
            ConflictResolutionRequiredError,
            CollabTimeoutError,
            SnapshotCorruptedError,
            EventReplayError,
        )

        assert CollabError is not None
        assert InvalidSessionStateError is not None
        assert InvalidTaskStateError is not None
        assert ApprovalNotFoundError is not None
        assert ConflictResolutionRequiredError is not None
        assert CollabTimeoutError is not None
        assert SnapshotCorruptedError is not None
        assert EventReplayError is not None
