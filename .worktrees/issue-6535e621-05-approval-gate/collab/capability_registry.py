"""
Agent capability registration and matching system.

This module provides the CapabilityRegistry class that stores agent capabilities
(strings like 'python_testing', 'debugging') and matches task descriptions to agents
via substring/keyword matching with score-based ranking.

The registry enables the coordinator to identify which agents can execute specific
tasks based on their registered capabilities.
"""

import time
from typing import Optional
from .types import AgentInfo


class CapabilityRegistry:
    """
    Registry for agent capabilities and task-to-agent matching.

    Stores agents with their capabilities and provides substring-based matching
    to find agents suitable for specific tasks. Match scores are computed based
    on the degree of overlap between task keywords and agent capabilities.
    """

    def __init__(self):
        """Initialize empty agent registry."""
        self._agents: dict[str, AgentInfo] = {}

    def register_agent(self, agent_id: str, name: str, capabilities: list[str]) -> None:
        """
        Store agent with capability strings.

        Args:
            agent_id: Unique identifier for the agent
            name: Human-readable name for the agent (used for metadata)
            capabilities: List of capability strings (e.g., ['python_testing', 'debugging'])

        Note:
            If agent_id already exists, it will be overwritten with new capabilities.
            The agent status is set to 'active' and joined_at/last_activity_at are
            set to the current timestamp.
        """
        current_time = time.time()
        self._agents[agent_id] = AgentInfo(
            agent_id=agent_id,
            capabilities=capabilities,
            status="active",
            current_task_id=None,
            joined_at=current_time,
            last_activity_at=current_time,
        )

    def find_agents_for_task(self, task_description: str) -> list[tuple[str, float]]:
        """
        Find agents matching a task description and return scored results.

        Uses substring matching to identify agents whose capabilities overlap
        with keywords in the task description. Scores are normalized to [0, 1],
        with exact matches scoring higher than partial matches.

        Args:
            task_description: Description of the task (e.g., 'debug Python tests')

        Returns:
            List of (agent_id, match_score) tuples sorted by score descending.
            Score is 0.0 if no capabilities match, up to 1.0 for perfect matches.
            Empty list returned if no agents registered or no matches found.
        """
        if not self._agents:
            return []

        # Extract keywords from task description (lowercase for case-insensitive matching)
        task_keywords = self._normalize_text(task_description)

        results: list[tuple[str, float]] = []

        for agent_id, agent_info in self._agents.items():
            score = self._calculate_match_score(task_keywords, agent_info["capabilities"])
            if score > 0.0:
                results.append((agent_id, score))

        # Sort by score descending (highest scores first)
        results.sort(key=lambda x: x[1], reverse=True)

        return results

    def deregister_agent(self, agent_id: str) -> None:
        """
        Remove agent from registry.

        Args:
            agent_id: ID of agent to remove

        Note:
            Does not raise error if agent_id not found (idempotent operation).
        """
        self._agents.pop(agent_id, None)

    def get_agent_capabilities(self, agent_id: str) -> list[str]:
        """
        Get capabilities for a registered agent.

        Args:
            agent_id: ID of agent to query

        Returns:
            List of capability strings for the agent

        Raises:
            KeyError: If agent_id not found in registry
        """
        if agent_id not in self._agents:
            raise KeyError(f"Agent '{agent_id}' not found in registry")
        return self._agents[agent_id]["capabilities"]

    def get_all_agents(self) -> dict[str, AgentInfo]:
        """
        Get all registered agents with metadata.

        Returns:
            Dictionary mapping agent_id to full AgentInfo TypedDict.
            Returns empty dict if no agents registered.
        """
        return dict(self._agents)

    # =========================================================================
    # Private helper methods for matching
    # =========================================================================

    @staticmethod
    def _normalize_text(text: str) -> set[str]:
        """
        Normalize text to lowercase tokens for matching.

        Splits on whitespace and punctuation to extract keywords.

        Args:
            text: Text to normalize (e.g., 'debug Python tests')

        Returns:
            Set of lowercase keywords
        """
        # Convert to lowercase and split on whitespace
        words = text.lower().split()

        # Remove punctuation and empty strings
        normalized = set()
        for word in words:
            # Remove common punctuation from start/end
            cleaned = word.strip('.,!?;:()[]{}"\'-')
            if cleaned:
                normalized.add(cleaned)

        return normalized

    @staticmethod
    def _calculate_match_score(
        task_keywords: set[str],
        agent_capabilities: list[str],
    ) -> float:
        """
        Calculate match score between task keywords and agent capabilities.

        Scoring algorithm:
        1. For each task keyword, find the best matching capability
        2. Exact matches (word equality) score highest: 1.0
        3. Capability contains keyword: score based on ratio of keyword length to capability length
           (longer capability containing keyword scores lower than shorter one)
        4. Keyword contains capability: 0.7 (partial match)
        5. Average the scores across all task keywords

        Args:
            task_keywords: Set of lowercase task keywords
            agent_capabilities: List of capability strings (not normalized)

        Returns:
            Match score in range [0.0, 1.0]
        """
        if not task_keywords or not agent_capabilities:
            return 0.0

        # Normalize capabilities to lowercase for matching
        norm_capabilities = {cap.lower() for cap in agent_capabilities}

        total_score = 0.0

        for keyword in task_keywords:
            best_match_score = 0.0

            for capability in norm_capabilities:
                # Exact match: highest score
                if keyword == capability:
                    best_match_score = 1.0
                    break
                # Keyword appears at word boundary in capability (e.g., 'debug' in 'debug_testing')
                elif (
                    keyword in capability
                    and (
                        keyword + "_" in capability
                        or keyword + "-" in capability
                        or capability.endswith(keyword)
                    )
                ):
                    # Score based on how much of the capability the keyword comprises
                    # Shorter capability = better match
                    keyword_ratio = len(keyword) / len(capability)
                    best_match_score = max(best_match_score, 0.8 * keyword_ratio)
                # Simple substring containment (both directions)
                elif keyword in capability or capability in keyword:
                    # Lower score for simple substring
                    best_match_score = max(best_match_score, 0.5)

            total_score += best_match_score

        # Normalize to [0, 1] by averaging across all keywords
        if len(task_keywords) > 0:
            score = total_score / len(task_keywords)
        else:
            score = 0.0

        return min(score, 1.0)
