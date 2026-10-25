"""Agents that decide moves under a time budget.

Importing the package imports the built-in agent modules, so their `register_agent`
decorators run and every built-in kind is available to `AgentSpec`.
"""

from hive.agents import minimax, negamax, random  # noqa: F401
