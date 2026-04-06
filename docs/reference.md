# AgentShell API Reference

AgentShell is a framework designed to build real-time collaborative AI agent terminal systems. It enables multiple autonomous agents to concurrently interact with shared terminal sessions, ensuring state consistency and conflict resolution using advanced techniques like Operational Transforms (OT) and Vector Clock synchronization.

This reference details the public interfaces of the modules found within the development worktrees.

---

## 📂 `.worktrees/issue-6535e621-05-approval-gate/collab/`

This module handles the core collaboration logic for the Approval Gate feature, managing sessions and capabilities.

### `collab/types.py`

Defines the fundamental data structures used across the collaboration system.

| Class/Function | Signature | Description | Example Usage |
| :--- | :--- | :--- | :--- |
| `AgentID` | `str` | A unique identifier for an autonomous agent. | `agent_id = AgentID("agent-alpha")` |
| `SessionID` | `str` | A unique identifier for a shared terminal session. | `session_id = SessionID("term-123")` |
| `Operation` | `dataclass` | Represents a single atomic change (e.g., keystroke, command execution) applied to the terminal state. | `op = Operation(type="input", data="hello")` |
| `VectorClock` | `dict[AgentID, int]` | Tracks the causality and versioning across agents. | `vc = VectorClock({"agent-a": 5, "agent-b": 2})` |

### `collab/capability_registry.py`

Manages which agents possess which permissions or capabilities within a shared session.

| Class/Function | Signature | Description | Example Usage |
| :--- | :--- | :--- | :--- |
| `CapabilityRegistry` | `class` | Stores and manages the set of capabilities granted to each `AgentID` for a given session. | `registry = CapabilityRegistry()` |
| `register_capability` | `(agent_id: AgentID, capability: str)` | Grants a specific capability to an agent. | `registry.register_capability(agent_id, "write_file")` |
| `has_capability` | `(agent_id: AgentID, capability: str) -> bool` | Checks if an agent possesses a required capability. | `if registry.has_capability(agent_id, "execute_command"): ...` |

### `collab/session_manager.py`

Handles the lifecycle and state management of collaborative terminal sessions.

| Class/Function | Signature | Description | Example Usage |
| :--- | :--- | :--- | :--- |
| `SessionManager` | `class` | Manages the creation, retrieval, and state persistence of active sessions. | `manager = SessionManager()` |
| `create_session` | `(initial_state: dict) -> SessionID` | Initializes a new collaborative session with a starting state. | `sid = manager.create_session({"cwd": "/home"})` |
| `get_session_state` | `(session_id: SessionID) -> dict` | Retrieves the current, synchronized state of a session. | `state = manager.get_session_state(sid)` |
| `apply_operation` | `(session_id: SessionID, op: Operation) -> bool` | Attempts to apply an operation to the session state, subject to validation. | `success = manager.apply_operation(sid, op)` |

### `collab/__init__.py`

(Acts as the primary entry point, typically re-exporting key components from the submodules.)

---

## 📂 `.worktrees/issue-6535e621-06-conflict-resolver/collab/`

This module focuses on the advanced logic required to merge concurrent operations safely, specifically implementing Operational Transforms (OT) and Vector Clock synchronization.

### `collab/types.py`

(Shares definitions with the Approval Gate module, but may include OT-specific structures.)

| Class/Function | Signature | Description | Example Usage |
| :--- | :--- | :--- | :--- |
| `Transform` | `dataclass` | Represents the transformation function needed to adjust one operation against another. | `t = Transform(op1, op2)` |

### `collab/capability_registry.py`

(Similar to the Approval Gate module, but may be specialized for conflict resolution permissions.)

### `collab/session_manager.py`

(Manages the session, but now integrates the conflict resolution layer before state commitment.)

### `collab/conflict_resolver.py`

The core module for handling concurrent edits and operations.

| Class/Function | Signature | Description | Example Usage |
| :--- | :--- | :--- | :--- |
| `ConflictResolver` | `class` | Implements the logic for applying operations while maintaining consistency across divergent histories. | `resolver = ConflictResolver()` |
| `transform_operation` | `(op_a: Operation, op_b: Operation) -> Operation` | Transforms `op_a` so it can be correctly applied after `op_b` has already been applied. | `transformed_op = resolver.transform_operation(op_new, op_committed)` |
| `merge_operations` | `(history: list[Operation], new_op: Operation, vc: VectorClock) -> tuple[list[Operation], Operation]` | Merges a new operation into the existing history, resolving conflicts via OT and updating the Vector Clock. | `new_history, final_op = resolver.merge_operations(history, op, vc)` |
| `resolve_divergence` | `(history_a: list[Operation], history_b: list[Operation]) -> tuple[list[Operation], list[Operation]]` | Merges two divergent histories into a single, consistent sequence. | `merged_a, merged_b = resolver.resolve_divergence(hist_a, hist_b)` |

---

## ⚙️ Core Implementation Detail: `terminal_coordinator`

While not explicitly listed as a separate file in the provided structure, the description implies the existence of a `terminal_coordinator` module responsible for the low-level PTY and OT integration.

**Conceptual Module: `terminal_coordinator`**

This module is responsible for the real-time interaction layer, utilizing Copy-On-Write (CoW) buffers and the `ConflictResolver`.

| Class/Function | Signature | Description | Example Usage |
| :--- | :--- | :--- | :--- |
| `VirtualTerminalBuffer` | `class` | Implements a CoW buffer structure for the terminal state, allowing atomic snapshots and efficient diffing. | `buffer = VirtualTerminalBuffer(initial_content)` |
| `TerminalCoordinator` | `class` | Orchestrates the PTY interaction, applying operations via OT, and managing the CoW buffer state. | `coordinator = TerminalCoordinator(session_id, resolver)` |
| `process_input` | `(raw_input: bytes, agent_id: AgentID) -> list[Operation]` | Takes raw terminal input, converts it into an `Operation`, and submits it for OT resolution. | `ops = coordinator.process_input(b'ls\n', agent_id)` |
| `apply_remote_op` | `(op: Operation, vc: VectorClock) -> bool` | Applies an operation received from another agent, triggering necessary transformations against the local state. | `success = coordinator.apply_remote_op(received_op, received_vc)` |