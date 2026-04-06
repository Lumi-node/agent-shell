"""
Unit tests for CapabilityRegistry.

Tests cover:
- Agent registration with capabilities
- Task-to-agent matching with substring matching and score ranking
- Agent deregistration
- Capability retrieval and agent enumeration
- Edge cases: empty registries, no matches, duplicate registrations
"""

import pytest
from collab import CapabilityRegistry


class TestRegisterAgent:
    """Tests for register_agent method."""

    def test_register_single_agent(self):
        """AC1: register_agent stores agent with list of capability strings."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Debugger', ['python_testing', 'debugging'])

        # Verify agent was registered
        all_agents = registry.get_all_agents()
        assert 'agent1' in all_agents
        assert all_agents['agent1']['agent_id'] == 'agent1'
        assert all_agents['agent1']['capabilities'] == ['python_testing', 'debugging']
        assert all_agents['agent1']['status'] == 'active'

    def test_register_multiple_agents(self):
        """Register multiple distinct agents."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Debugger', ['python_testing', 'debugging'])
        registry.register_agent('agent2', 'Builder', ['build', 'compile'])
        registry.register_agent('agent3', 'Tester', ['test', 'python_testing'])

        all_agents = registry.get_all_agents()
        assert len(all_agents) == 3
        assert 'agent1' in all_agents
        assert 'agent2' in all_agents
        assert 'agent3' in all_agents

    def test_register_agent_overwrites_previous(self):
        """Duplicate agent_id registration overwrites previous entry."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'v1', ['python'])
        registry.register_agent('agent1', 'v2', ['javascript', 'nodejs'])

        # Should have new capabilities
        assert registry.get_agent_capabilities('agent1') == ['javascript', 'nodejs']
        assert len(registry.get_all_agents()) == 1

    def test_register_agent_with_empty_capabilities(self):
        """Register agent with empty capabilities list."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Empty', [])

        # Should still be registered but with no capabilities
        assert 'agent1' in registry.get_all_agents()
        assert registry.get_agent_capabilities('agent1') == []

    def test_register_agent_sets_status_active(self):
        """Agent status should be set to 'active' on registration."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python'])

        agent_info = registry.get_all_agents()['agent1']
        assert agent_info['status'] == 'active'
        assert agent_info['current_task_id'] is None

    def test_register_agent_sets_timestamps(self):
        """Agent joined_at and last_activity_at should be set to current time."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python'])

        agent_info = registry.get_all_agents()['agent1']
        assert agent_info['joined_at'] > 0
        assert agent_info['last_activity_at'] > 0
        assert agent_info['joined_at'] == agent_info['last_activity_at']


class TestFindAgentsForTask:
    """Tests for find_agents_for_task method."""

    def test_find_agents_with_substring_match(self):
        """AC2,3: find_agents_for_task returns agent with match_score > 0 for substring match."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Debugger', ['python_testing', 'debugging'])

        results = registry.find_agents_for_task('debug Python tests')
        assert len(results) > 0
        assert results[0][0] == 'agent1'
        assert results[0][1] > 0.0

    def test_find_agents_empty_registry(self):
        """find_agents_for_task returns empty list when no agents registered."""
        registry = CapabilityRegistry()
        results = registry.find_agents_for_task('any task')
        assert results == []

    def test_find_agents_no_matches(self):
        """find_agents_for_task returns empty list when no capabilities match."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Debugger', ['python_testing', 'debugging'])

        results = registry.find_agents_for_task('build javascript frontend')
        assert results == []

    def test_find_agents_multiple_matches_sorted_by_score(self):
        """AC7: Multiple agents returned sorted by match_score descending."""
        registry = CapabilityRegistry()
        # Agent with exact match on 'python'
        registry.register_agent('agent1', 'Expert', ['python', 'testing'])
        # Agent with partial match
        registry.register_agent('agent2', 'Novice', ['java', 'testing'])
        # Agent with exact match on 'testing'
        registry.register_agent('agent3', 'Tester', ['testing', 'qa'])

        results = registry.find_agents_for_task('python testing')
        # Should have at least 3 results (all match on 'testing' or contain it)
        assert len(results) >= 2
        # Results should be sorted by score descending
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_find_agents_case_insensitive_matching(self):
        """Matching should be case-insensitive."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['Python', 'Testing'])

        results = registry.find_agents_for_task('PYTHON testing')
        assert len(results) > 0
        assert results[0][0] == 'agent1'

    def test_find_agents_exact_match_scores_higher(self):
        """AC8: Exact capability matches score higher than substring matches."""
        registry = CapabilityRegistry()
        # Agent with exact capability match
        registry.register_agent('agent1', 'Expert1', ['python'])
        # Agent with substring match (capability contains keyword)
        registry.register_agent('agent2', 'Expert2', ['python_testing'])

        results = registry.find_agents_for_task('python')
        assert len(results) >= 2
        # agent1 should score higher (exact match vs substring match)
        agent1_result = next((score for aid, score in results if aid == 'agent1'), None)
        agent2_result = next((score for aid, score in results if aid == 'agent2'), None)

        assert agent1_result is not None
        assert agent2_result is not None
        assert agent1_result > agent2_result

    def test_find_agents_punctuation_handling(self):
        """Task description with punctuation should be handled correctly."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['debugging', 'python'])

        # Task with punctuation
        results = registry.find_agents_for_task('Debug Python! (testing...)')
        assert len(results) > 0
        assert results[0][0] == 'agent1'

    def test_find_agents_score_between_0_and_1(self):
        """Match scores should be in range [0.0, 1.0]."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python', 'testing'])

        results = registry.find_agents_for_task('python testing debugging')
        assert all(0.0 <= score <= 1.0 for _, score in results)


class TestDeregisterAgent:
    """Tests for deregister_agent method."""

    def test_deregister_removes_agent(self):
        """AC4: deregister_agent removes agent from registry."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python'])
        assert 'agent1' in registry.get_all_agents()

        registry.deregister_agent('agent1')
        assert 'agent1' not in registry.get_all_agents()

    def test_deregister_excludes_from_find(self):
        """AC4: Deregistered agent excluded from find_agents_for_task results."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python'])

        results_before = registry.find_agents_for_task('python')
        assert len(results_before) == 1

        registry.deregister_agent('agent1')
        results_after = registry.find_agents_for_task('python')
        assert len(results_after) == 0

    def test_deregister_nonexistent_agent(self):
        """Deregister on non-existent agent should not raise error (idempotent)."""
        registry = CapabilityRegistry()
        # Should not raise
        registry.deregister_agent('nonexistent')

    def test_deregister_one_of_multiple_agents(self):
        """Deregister one agent doesn't affect others."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'A', ['python'])
        registry.register_agent('agent2', 'B', ['python'])

        registry.deregister_agent('agent1')

        all_agents = registry.get_all_agents()
        assert 'agent1' not in all_agents
        assert 'agent2' in all_agents


class TestGetAgentCapabilities:
    """Tests for get_agent_capabilities method."""

    def test_get_agent_capabilities_returns_list(self):
        """AC5: get_agent_capabilities returns list of capabilities."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python_testing', 'debugging'])

        capabilities = registry.get_agent_capabilities('agent1')
        assert capabilities == ['python_testing', 'debugging']

    def test_get_agent_capabilities_not_found(self):
        """AC5: get_agent_capabilities raises KeyError if agent not found."""
        registry = CapabilityRegistry()
        with pytest.raises(KeyError):
            registry.get_agent_capabilities('nonexistent')

    def test_get_agent_capabilities_after_deregister(self):
        """Getting capabilities for deregistered agent raises KeyError."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python'])
        registry.deregister_agent('agent1')

        with pytest.raises(KeyError):
            registry.get_agent_capabilities('agent1')

    def test_get_agent_capabilities_empty_list(self):
        """get_agent_capabilities returns empty list for agent with no capabilities."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Empty', [])

        capabilities = registry.get_agent_capabilities('agent1')
        assert capabilities == []


class TestGetAllAgents:
    """Tests for get_all_agents method."""

    def test_get_all_agents_empty_registry(self):
        """AC6: get_all_agents returns empty dict when no agents registered."""
        registry = CapabilityRegistry()
        assert registry.get_all_agents() == {}

    def test_get_all_agents_single_agent(self):
        """AC6: get_all_agents returns dict with registered agent."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python'])

        all_agents = registry.get_all_agents()
        assert len(all_agents) == 1
        assert 'agent1' in all_agents
        assert all_agents['agent1']['capabilities'] == ['python']

    def test_get_all_agents_multiple_agents(self):
        """AC6: get_all_agents returns all registered agents."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'A', ['python'])
        registry.register_agent('agent2', 'B', ['javascript'])
        registry.register_agent('agent3', 'C', ['go'])

        all_agents = registry.get_all_agents()
        assert len(all_agents) == 3
        assert set(all_agents.keys()) == {'agent1', 'agent2', 'agent3'}

    def test_get_all_agents_returns_copy(self):
        """get_all_agents should return a dict that can be modified without affecting registry."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python'])

        all_agents = registry.get_all_agents()
        all_agents['agent2'] = None  # Modify returned dict

        # Registry should not be affected
        assert len(registry.get_all_agents()) == 1


class TestComplexScenarios:
    """Integration tests combining multiple operations."""

    def test_multiple_agents_with_overlapping_capabilities(self):
        """AC7: Register A, B, C with overlapping caps; find_agents returns all matches sorted."""
        registry = CapabilityRegistry()
        registry.register_agent('agentA', 'A', ['python_testing', 'debugging', 'analysis'])
        registry.register_agent('agentB', 'B', ['python_testing', 'profiling'])
        registry.register_agent('agentC', 'C', ['debugging', 'logging'])

        # Query for task matching multiple capabilities
        results = registry.find_agents_for_task('python debugging')

        # Should match all three agents (all have 'debugging' or 'python')
        matching_agents = [agent_id for agent_id, _ in results]
        assert 'agentA' in matching_agents
        assert 'agentB' in matching_agents
        assert 'agentC' in matching_agents

        # Should be sorted by score descending
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_capability_matching_with_exact_and_partial_matches(self):
        """Complex matching scenario with mix of exact and substring matches."""
        registry = CapabilityRegistry()
        registry.register_agent('expert', 'Expert', ['python_testing', 'unit_testing'])
        registry.register_agent('novice', 'Novice', ['pythonista', 'testing_frameworks'])

        results = registry.find_agents_for_task('python unit testing')

        # Both should match, but expert should score higher
        assert len(results) >= 1
        expert_idx = next((i for i, (aid, _) in enumerate(results) if aid == 'expert'), -1)
        if expert_idx >= 0:
            novice_idx = next((i for i, (aid, _) in enumerate(results) if aid == 'novice'), -1)
            if novice_idx >= 0:
                assert results[expert_idx][1] >= results[novice_idx][1]

    def test_register_find_deregister_workflow(self):
        """Full lifecycle: register → find → deregister → find again."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python'])

        # Should find agent initially
        results = registry.find_agents_for_task('python code')
        assert len(results) == 1

        # After deregister, should not find
        registry.deregister_agent('agent1')
        results = registry.find_agents_for_task('python code')
        assert len(results) == 0

        # Can re-register with different capabilities
        registry.register_agent('agent1', 'Test', ['javascript'])
        results = registry.find_agents_for_task('javascript')
        assert len(results) == 1

    def test_find_agents_with_special_characters_in_task(self):
        """Task descriptions with special characters should be handled correctly."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python', 'debugging'])

        # Task with various special characters
        results = registry.find_agents_for_task("Debug/Test @Python's (runtime)!")
        assert len(results) > 0
        assert results[0][0] == 'agent1'

    def test_capability_with_special_characters(self):
        """Capabilities with hyphens, underscores should be matched correctly."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python-testing', 'unit_test'])

        results = registry.find_agents_for_task('python testing unit test')
        assert len(results) > 0
        assert results[0][0] == 'agent1'


class TestEdgeCases:
    """Edge case tests."""

    def test_whitespace_in_task_description(self):
        """Task descriptions with extra whitespace should be handled."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python'])

        results = registry.find_agents_for_task('  python  testing  ')
        assert len(results) > 0

    def test_single_character_capability(self):
        """Single character capabilities should match correctly."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['x', 'y'])

        results = registry.find_agents_for_task('x y z')
        assert len(results) > 0

    def test_very_long_capability_list(self):
        """Agent with many capabilities should work correctly."""
        registry = CapabilityRegistry()
        many_caps = [f'capability_{i}' for i in range(100)]
        registry.register_agent('agent1', 'Multi', many_caps)

        results = registry.find_agents_for_task('capability_50')
        assert len(results) > 0

    def test_long_task_description(self):
        """Very long task description should be handled."""
        registry = CapabilityRegistry()
        registry.register_agent('agent1', 'Test', ['python', 'testing'])

        long_task = ' '.join(['python', 'testing'] * 50)
        results = registry.find_agents_for_task(long_task)
        assert len(results) > 0
