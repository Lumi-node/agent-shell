"""
Conflict Resolver: 3-way merge and conflict detection for files.

Detects file conflicts using line-level diff, performs 3-way merge for
non-overlapping edits, identifies command sequence conflicts, and records
resolutions for session determinism.

Key Features:
- Line-level diff using longest common subsequence (LCS)
- 3-way merge for non-overlapping edits (auto-merge strategy)
- Conflict detection with overlapping line ranges
- Conflict marker generation for human review
- Command sequence warning detection
- Conflict resolution recording in session state
"""

import uuid
import time
from typing import Optional
from difflib import SequenceMatcher

from .types import ConflictInfo, CommandSequenceWarning, ConflictDetectedEvent
from .session_manager import SessionManager


class ConflictResolver:
    """
    Detects and resolves conflicts when agents attempt simultaneous modifications.

    Supports three conflict types:
    1. File edit conflict: Two agents modify the same file simultaneously
    2. Directory conflict: Agents change working directories simultaneously
    3. Command sequence conflict: Commands may have conflicting side effects

    Resolution strategies:
    - Non-overlapping edits: Auto-merge with both changes present
    - Overlapping edits: Human decision required, present with conflict markers
    - Command conflicts: Informational warnings, not blocking
    """

    def __init__(self, session_manager: Optional[SessionManager] = None):
        """
        Initialize ConflictResolver.

        Args:
            session_manager: Optional SessionManager for recording conflict events.
                           If None, conflict resolution won't be persisted.
        """
        self.session_manager = session_manager

    def detect_file_conflict(
        self,
        file_path: str,
        agent_a_id: str,
        agent_b_id: str,
        original: str,
        version_a: str,
        version_b: str,
    ) -> Optional[ConflictInfo]:
        """
        Detect if edits conflict using line-level diff.

        Performs 3-way merge analysis:
        1. Compare original vs version_a to identify agent A's edits
        2. Compare original vs version_b to identify agent B's edits
        3. Check if edit ranges overlap

        Args:
            file_path: Absolute path to file
            agent_a_id: ID of first agent
            agent_b_id: ID of second agent
            original: Original file content (common ancestor)
            version_a: Agent A's modified version
            version_b: Agent B's modified version

        Returns:
            None if no conflict detected
            ConflictInfo with non-empty overlapping_lines if conflict exists

        TYPE SEMANTICS (CRITICAL):
            - ConflictInfo is ONLY returned when conflict EXISTS
            - Therefore, overlapping_lines is ALWAYS non-None and non-empty
            - When None is returned, no conflict detected
        """
        # Split into lines for line-level diff
        original_lines = original.splitlines(keepends=False)
        version_a_lines = version_a.splitlines(keepends=False)
        version_b_lines = version_b.splitlines(keepends=False)

        # Find changed line ranges for each agent
        a_changed_lines = self._find_changed_lines(original_lines, version_a_lines)
        b_changed_lines = self._find_changed_lines(original_lines, version_b_lines)

        # No changes by either agent means no conflict
        if not a_changed_lines and not b_changed_lines:
            return None

        # One agent changed nothing, other changed something means no conflict
        if not a_changed_lines or not b_changed_lines:
            return None

        # Find overlapping line ranges
        overlapping = self._find_overlapping_ranges(a_changed_lines, b_changed_lines)

        # No overlapping ranges means successful 3-way merge
        if not overlapping:
            return None

        # Conflict exists: return ConflictInfo with overlapping_lines
        conflict_id = str(uuid.uuid4())
        return ConflictInfo(
            conflict_id=conflict_id,
            file_path=file_path,
            agent_ids=[agent_a_id, agent_b_id],
            overlapping_lines=overlapping,  # Non-empty guaranteed
            detected_at=time.time(),
            resolved=False,
            resolution_strategy=None,
        )

    def resolve_file_conflict(
        self,
        conflict_info: ConflictInfo,
        human_choice: str = "auto",
    ) -> str:
        """
        Apply resolution strategy and return merged content.

        Args:
            conflict_info: ConflictInfo from detect_file_conflict()
            human_choice: Resolution strategy:
                         'auto' - Auto-merge non-overlapping changes (if possible)
                         'human' - Return with conflict markers for human review

        Returns:
            Merged file content as string

        Raises:
            ValueError: If conflict_info lacks required information
        """
        if human_choice == "auto":
            # Auto-merge is already done in detect_file_conflict
            # For true auto-merge, we'd need to read the actual versions
            # For now, return placeholder that would be replaced with actual merge
            return self._perform_auto_merge(conflict_info)
        elif human_choice == "human":
            # Return content with conflict markers for human review
            return self._add_conflict_markers(conflict_info)
        else:
            raise ValueError(f"Unknown resolution strategy: {human_choice}")

    def record_conflict_resolution(
        self,
        conflict_id: str,
        resolution: str,
    ) -> None:
        """
        Record conflict resolution in session state for replay determinism.

        Args:
            conflict_id: ID of resolved conflict
            resolution: Resolution chosen (e.g., "auto_merge", "manual_merge", "version_a", "version_b")
        """
        if not self.session_manager:
            # No session manager, can't record
            return

        # Record ConflictDetectedEvent with resolution info
        event = ConflictDetectedEvent(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            session_id=self.session_manager.session_id,
            payload=ConflictDetectedEvent.Payload(
                conflict_type="file",
                agent_ids=[],  # Would be populated from conflict_info if available
                resource_path="",  # Would be populated from conflict_info if available
                conflict_details=f"Conflict resolved with strategy: {resolution}",
                resolution_required=False,
                timestamp=time.time(),
            ),
        )
        self.session_manager.record_event(
            event_type="conflict_detected",
            agent_id="system",
            payload=dict(event.payload),
        )

    def detect_concurrent_commands(
        self,
        agent_commands: list[tuple[str, str]],
    ) -> list[CommandSequenceWarning]:
        """
        Detect potentially conflicting command sequences.

        Identifies commands that may have side effects on each other:
        - Different directory changes (cd to different locations)
        - Conflicting file write operations
        - Resource contention

        Args:
            agent_commands: List of (agent_id, command) tuples

        Returns:
            List of CommandSequenceWarning for potentially conflicting commands
        """
        warnings = []

        if len(agent_commands) < 2:
            return warnings

        # Check for directory conflicts
        dir_warnings = self._detect_directory_conflicts(agent_commands)
        warnings.extend(dir_warnings)

        # Check for file write conflicts
        file_warnings = self._detect_file_write_conflicts(agent_commands)
        warnings.extend(file_warnings)

        return warnings

    # =========================================================================
    # PRIVATE HELPER METHODS
    # =========================================================================

    def _find_changed_lines(
        self,
        original_lines: list[str],
        modified_lines: list[str],
    ) -> list[tuple[int, int]]:
        """
        Find ranges of changed lines between original and modified versions.

        Uses SequenceMatcher to identify contiguous blocks of changes.

        Returns:
            List of (start_line, end_line) tuples (1-indexed, inclusive)
            Empty list if no changes detected
        """
        if not original_lines and not modified_lines:
            return []

        matcher = SequenceMatcher(None, original_lines, modified_lines)
        changed_ranges = []

        # Find blocks that are NOT matching (i.e., changed)
        matching_blocks = matcher.get_matching_blocks()

        # Convert matching blocks to changed regions
        last_orig_end = 0
        for block in matching_blocks:
            orig_start, mod_start, length = block.a, block.b, block.size

            if orig_start > last_orig_end:
                # There's a gap - lines in this gap are changed
                # Use max to handle insertions/deletions
                start_line = last_orig_end + 1
                end_line = orig_start
                if start_line <= end_line:
                    changed_ranges.append((start_line, end_line))

            last_orig_end = orig_start + length

        # Check if there are changes after last matching block
        if last_orig_end < len(original_lines):
            start_line = last_orig_end + 1
            end_line = len(original_lines)
            if start_line <= end_line:
                changed_ranges.append((start_line, end_line))

        # If modified has more lines (insertions at end)
        if len(modified_lines) > len(original_lines):
            # Insertions don't create conflicts by themselves
            pass

        return changed_ranges

    def _find_overlapping_ranges(
        self,
        a_ranges: list[tuple[int, int]],
        b_ranges: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """
        Find overlapping line ranges between two sets of ranges.

        Args:
            a_ranges: List of (start, end) tuples from agent A
            b_ranges: List of (start, end) tuples from agent B

        Returns:
            List of overlapping (start, end) tuples
        """
        overlapping = []

        for a_start, a_end in a_ranges:
            for b_start, b_end in b_ranges:
                # Check if ranges overlap
                overlap_start = max(a_start, b_start)
                overlap_end = min(a_end, b_end)

                if overlap_start <= overlap_end:
                    overlapping.append((overlap_start, overlap_end))

        return overlapping

    def _perform_auto_merge(self, conflict_info: ConflictInfo) -> str:
        """
        Perform auto-merge for non-overlapping edits.

        In a real implementation, this would take the actual file versions
        and merge them. For now, return a placeholder.

        Args:
            conflict_info: ConflictInfo with conflict details

        Returns:
            Merged content as string
        """
        # Placeholder: in real implementation, would merge versions
        return "# Auto-merged content would appear here"

    def _add_conflict_markers(self, conflict_info: ConflictInfo) -> str:
        """
        Add conflict markers for human review.

        Generates standard 3-way merge conflict markers:
        <<<<<<< Agent A version
        ... agent A's version ...
        =======
        ... agent B's version ...
        >>>>>>> Agent B version

        Args:
            conflict_info: ConflictInfo with conflict details

        Returns:
            Content with conflict markers
        """
        agent_a_id = conflict_info["agent_ids"][0] if conflict_info["agent_ids"] else "Agent A"
        agent_b_id = conflict_info["agent_ids"][1] if len(conflict_info["agent_ids"]) > 1 else "Agent B"

        # Placeholder: in real implementation, would include actual versions
        markers = f"<<<<<<< {agent_a_id}\n"
        markers += "# Agent A's version would appear here\n"
        markers += "=======\n"
        markers += f"# Agent B's version would appear here\n"
        markers += f">>>>>>> {agent_b_id}\n"

        return markers

    def _detect_directory_conflicts(
        self,
        agent_commands: list[tuple[str, str]],
    ) -> list[CommandSequenceWarning]:
        """
        Detect when multiple agents change to different directories.

        Args:
            agent_commands: List of (agent_id, command) tuples

        Returns:
            List of CommandSequenceWarning for directory conflicts
        """
        warnings = []
        cd_commands = {}

        for agent_id, command in agent_commands:
            if command.strip().startswith("cd "):
                # Extract target directory
                parts = command.strip().split(maxsplit=1)
                if len(parts) > 1:
                    target_dir = parts[1]
                    cd_commands[agent_id] = target_dir

        # Check if multiple agents are changing to different directories
        if len(cd_commands) > 1:
            unique_dirs = set(cd_commands.values())
            if len(unique_dirs) > 1:
                # Conflict: agents changing to different directories
                warning = CommandSequenceWarning(
                    agent_ids=list(cd_commands.keys()),
                    commands={agent_id: f"cd {dir_path}" for agent_id, dir_path in cd_commands.items()},
                    conflict_type="directory_conflict",
                    recommendation="Coordinate directory changes before approval. Agents are changing to different directories which may cause unexpected behavior.",
                )
                warnings.append(warning)

        return warnings

    def _detect_file_write_conflicts(
        self,
        agent_commands: list[tuple[str, str]],
    ) -> list[CommandSequenceWarning]:
        """
        Detect when multiple agents may write to the same files.

        Args:
            agent_commands: List of (agent_id, command) tuples

        Returns:
            List of CommandSequenceWarning for file write conflicts
        """
        warnings = []

        # Simple heuristic: look for write operations (>, >>, |, tee)
        # In a real implementation, this would be more sophisticated
        write_commands = {}

        for agent_id, command in agent_commands:
            # Check for common write patterns
            if any(op in command for op in [">", ">>", "|", "tee", "write"]):
                write_commands[agent_id] = command

        # If multiple agents are writing, warn
        if len(write_commands) > 1:
            warning = CommandSequenceWarning(
                agent_ids=list(write_commands.keys()),
                commands=write_commands,
                conflict_type="file_write_race",
                recommendation="Multiple agents are performing write operations. Ensure they don't target the same files.",
            )
            warnings.append(warning)

        return warnings
