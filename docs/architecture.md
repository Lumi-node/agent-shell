# AgentShell Architecture

AgentShell is designed to be a sophisticated, real-time collaborative AI agent terminal system. Its primary goal is to allow multiple autonomous agents to interact concurrently within shared terminal sessions. This system must manage the complexities of concurrent state modification—such as simultaneous command execution, file editing, and task coordination—by employing advanced concurrency control mechanisms like Operational Transforms (OT) and vector clock synchronization to ensure absolute state consistency across all participating agents.

## System Overview

The architecture is modular, separating concerns related to session management, capability definition, and the core logic for conflict resolution. The system revolves around maintaining a consistent, shared state for each terminal session. When multiple agents attempt to modify the terminal buffer (e.g., typing input or receiving output), the system intercepts these operations. The Conflict Resolver module uses OT to transform incoming operations against the current state, ensuring that the final state reflects all intended changes without corruption, while the Session Manager handles the lifecycle and context of these collaborative sessions.

## Module Relationships

```mermaid
graph TD
    subgraph Core Collaboration Logic
        CR[ConflictResolver]
        SR[SessionManager]
        CR_Reg[CapabilityRegistry (Conflict)]
        SR_Reg[CapabilityRegistry (Session)]
    end

    subgraph Session Management
        SM[SessionManager]
        CT[TerminalCoordinator]
    end

    subgraph Data & Types
        T[Types]
    end

    CR --> CR_Reg
    CR --> SM
    SR --> SR_Reg
    SR --> T
    CT --> SM
    CT --> CR
    CR --> T
    SM --> T

    style CR fill:#f9f,stroke:#333,stroke-width:2px
    style CT fill:#ccf,stroke:#333,stroke-width:2px
```

## Module Descriptions

The architecture is split across two primary functional areas, corresponding to the two main feature sets: **Approval Gate** and **Conflict Resolver**. While the core concepts are similar, the Conflict Resolver is the focus for the real-time terminal functionality.

### Shared/General Modules

*   **`collab/types.py`**: Defines the core data structures used across the system. This includes definitions for operations (e.g., keystrokes, command executions), session metadata, and the structure for vector clocks used for synchronization.
*   **`collab/capability_registry.py`**: A centralized registry that defines and manages the capabilities available within a specific collaboration context (e.g., "read file," "execute command," "modify buffer"). This ensures that agents only attempt operations they are authorized to perform within that session.

### Approval Gate Modules (Contextual/Gatekeeping)

These modules handle the logic for gating or approving actions before they proceed to the core execution path.

*   **`.worktrees/issue-6535e621-05-approval-gate/collab/session_manager.py`**: Manages the lifecycle of sessions within the approval gate context. It tracks which agents are participating and manages the state transitions required for approval workflows.
*   **`.worktrees/issue-6535e621-05-approval-gate/collab/capability_registry.py`**: Defines the capabilities relevant to the approval gate process, dictating what actions require explicit sign-off.

### Conflict Resolver Modules (Real-Time Terminal Focus)

These modules implement the core logic for handling concurrent, real-time modifications to the terminal buffer.

*   **`.worktrees/issue-6535e621-06-conflict-resolver/collab/session_manager.py`**: Manages the state and context of the terminal sessions being actively edited. It tracks the current version of the terminal buffer and the associated synchronization metadata (like vector clocks).
*   **`.worktrees/issue-6535e621-06-conflict-resolver/collab/conflict_resolver.py`**: This is the heart of the concurrency control. It receives incoming operations from agents, compares them against the current state, and applies Operational Transforms (OT) to transform the incoming operation so it can be correctly applied to the current state, thereby resolving conflicts deterministically.
*   **`.worktrees/issue-6535e621-06-conflict-resolver/collab/capability_registry.py`**: Defines the specific capabilities required for terminal interaction (e.g., "send_input," "receive_output").

### Core Execution Module

*   **`terminal_coordinator` (Conceptual/Implied)**: This module orchestrates the entire process. It interfaces with the `SessionManager` to retrieve the current session state, passes incoming operations to the `ConflictResolver`, and manages the underlying copy-on-write virtual terminal buffers. It is responsible for applying the transformed operations back to the buffer and broadcasting the resulting state change to all connected agents.

## Data Flow Explanation

The data flow in a concurrent operation (e.g., Agent A types 'H' while Agent B types 'W' into the same terminal buffer) follows this path:

1.  **Operation Generation**: Agent A generates an operation $O_A$ (e.g., `Insert('H')`) and attaches its current vector clock $VC_A$.
2.  **Ingestion**: $O_A$ is sent to the `TerminalCoordinator`.
3.  **State Retrieval**: The `TerminalCoordinator` queries the `SessionManager` to get the current terminal buffer state $S_{current}$ and its associated vector clock $VC_{current}$.
4.  **Conflict Resolution**: $O_A$ is passed to the `ConflictResolver`. The resolver uses $VC_{current}$ and $VC_A$ to determine if $O_A$ conflicts with any operations already applied since $VC_A$ was generated.
5.  **Transformation**: If a conflict exists, the `ConflictResolver` applies the OT algorithm to transform $O_A$ into $O'_A$, ensuring $O'_A$ is valid against $S_{current}$.
6.  **Application**: The `TerminalCoordinator` applies the transformed operation $O'_A$ to the copy-on-write buffer, resulting in a new state $S_{new}$.
7.  **Synchronization**: The `SessionManager` updates the session state to $S_{new}$ and increments the vector clock to $VC_{new}$.
8.  **Broadcast**: $S_{new}$ and $VC_{new}$ are broadcast to all connected agents, allowing them to update their local views of the terminal state.

This cycle ensures that even if operations arrive out of order or concurrently, the final state $S_{new}$ is mathematically consistent across all participants.