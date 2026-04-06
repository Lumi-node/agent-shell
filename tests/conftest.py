"""
Pytest configuration and fixtures for collab test suite.

This module provides reusable fixtures for all major collab components:
- SessionManager
- ApprovalGate
- ConflictResolver
- PTYExecutor
- CapabilityRegistry
- AgentCoordinator
"""

import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def temp_session_dir():
    """Provide a temporary directory for session storage."""
    temp_dir = tempfile.mkdtemp(prefix="collab_test_")
    yield temp_dir
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def session_manager_fixture(temp_session_dir):
    """
    Fixture for SessionManager instance.

    Provides a SessionManager configured with a temporary session storage directory.
    """
    from collab.session_manager import SessionManager

    return SessionManager("test_session", temp_session_dir)


@pytest.fixture
def approval_gate_fixture():
    """
    Fixture for ApprovalGate instance.

    When implemented, this will provide an ApprovalGate configured for testing.
    """
    # Placeholder for ApprovalGate fixture
    # Actual implementation will be added when ApprovalGate is implemented
    pass


@pytest.fixture
def conflict_resolver_fixture():
    """
    Fixture for ConflictResolver instance.

    When implemented, this will provide a ConflictResolver configured for testing.
    """
    # Placeholder for ConflictResolver fixture
    # Actual implementation will be added when ConflictResolver is implemented
    pass


@pytest.fixture
def pty_executor_fixture():
    """
    Fixture for PTYExecutor instance.

    When implemented, this will provide a PTYExecutor configured for testing.
    """
    # Placeholder for PTYExecutor fixture
    # Actual implementation will be added when PTYExecutor is implemented
    pass


@pytest.fixture
def capability_registry_fixture():
    """
    Fixture for CapabilityRegistry instance.

    When implemented, this will provide a CapabilityRegistry configured for testing.
    """
    # Placeholder for CapabilityRegistry fixture
    # Actual implementation will be added when CapabilityRegistry is implemented
    pass


@pytest.fixture
def agent_coordinator_fixture():
    """
    Fixture for AgentCoordinator instance.

    When implemented, this will provide an AgentCoordinator configured for testing.
    """
    # Placeholder for AgentCoordinator fixture
    # Actual implementation will be added when AgentCoordinator is implemented
    pass
