# 🚀 AgentShell Quick Start Guide

AgentShell is a framework designed to build real-time, collaborative AI agent terminal systems. It allows multiple autonomous agents to interact concurrently within shared terminal sessions, ensuring state consistency through advanced synchronization mechanisms like Operational Transforms (OT) and Vector Clocks.

This guide will get you up and running with the core components.

## 📦 Installation

Assuming you have a Python environment set up, you can install AgentShell:

```bash
pip install agent_shell
```

## 🏗️ Core Concepts

AgentShell revolves around managing shared state across multiple agents. Key concepts include:

*   **Session Management:** Tracking the state and participants of a shared terminal session (`session_manager.py`).
*   **Capability Registry:** Defining what actions agents are allowed to perform (`capability_registry.py`).
*   **Conflict Resolution:** Using OT and Vector Clocks to merge concurrent changes safely (`conflict_resolver.py`).
*   **Terminal Coordination:** The core logic for handling concurrent PTY operations using Copy-On-Write (CoW) buffers (`terminal_coordinator` - *Note: This module is implied by the goal and is the central piece of the system*).

## 🛠️ Usage Examples

The following examples demonstrate how to initialize and interact with the core components of AgentShell.

### Example 1: Initializing a Collaborative Session

This example shows how to set up a basic session and register capabilities for two agents.

```python
from agent_shell.collab.session_manager import SessionManager
from agent_shell.collab.capability_registry import CapabilityRegistry

# 1. Initialize the Capability Registry
registry = CapabilityRegistry()
registry.register_capability("file_edit", "Allows modification of shared files.")
registry.register_capability("command_execute", "Allows running shell commands.")

# 2. Initialize the Session Manager
session_id = "terminal_session_001"
session_manager = SessionManager(session_id, registry)

print(f"Session '{session_id}' initialized.")
print(f"Available capabilities: {session_manager.get_available_capabilities()}")

# Simulate adding agents
agent_a_id = "AgentAlpha"
agent_b_id = "AgentBeta"
session_manager.add_agent(agent_a_id)
session_manager.add_agent(agent_b_id)

print(f"Agents {agent_a_id} and {agent_b_id} joined the session.")
```

### Example 2: Simulating a Conflict Resolution Event

This demonstrates how the `ConflictResolver` would handle two agents attempting to modify the same terminal buffer state concurrently.

```python
from agent_shell.collab.conflict_resolver import ConflictResolver
from agent_shell.collab.types import TerminalBufferState

# Assume we have an initial state
initial_state = TerminalBufferState(content="Welcome to the shared terminal.\n")

# Initialize the resolver
resolver = ConflictResolver()

# Agent A makes a change (Operation A)
op_a = {"type": "insert", "position": 0, "text": "Agent A typed: "}
state_after_a = resolver.apply_operation(initial_state, op_a)

# Agent B makes a conflicting change (Operation B) based on the *original* state
op_b = {"type": "insert", "position": 0, "text": "Agent B typed: "}

# Resolve the conflict between Op B and the state resulting from Op A
# The resolver uses OT logic to transform Op B against Op A's changes.
resolved_state = resolver.resolve_conflict(state_after_a, op_b)

print("\n--- Conflict Resolution Simulation ---")
print(f"Initial Content: {initial_state.content}")
print(f"State after A: {state_after_a.content}")
print(f"Final Resolved Content: {resolved_state.content}")
```

### Example 3: Coordinating a Terminal Operation (Conceptual)

This illustrates the high-level flow where the `terminal_coordinator` (the module responsible for CoW and OT application) manages the interaction between agents and the virtual terminal.

```python
# NOTE: This requires the full implementation of terminal_coordinator,
# but shows the intended interface.

from agent_shell.terminal_coordinator import TerminalCoordinator
from agent_shell.collab.session_manager import SessionManager

# Setup (using components from Example 1)
session_manager = SessionManager("terminal_session_002", ...)
coordinator = TerminalCoordinator(session_manager)

# Agent Alpha wants to execute a command
agent_alpha_id = "AgentAlpha"
command = "ls -l"

print("\n--- Terminal Coordination Simulation ---")
print(f"Agent {agent_alpha_id} requests command execution: '{command}'")

# The coordinator handles:
# 1. Checking capabilities via SessionManager.
# 2. Applying the command execution operation to the CoW buffer.
# 3. Generating an OT transformation if another agent is typing concurrently.
try:
    output_stream = coordinator.execute_command(agent_alpha_id, command)
    print(f"Command executed successfully. Output received.")
    print(f"Terminal Output Snippet: {output_stream[:50]}...")
except Exception as e:
    print(f"Error during coordination: {e}")
```