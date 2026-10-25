"""Routes that describe the registered agent kinds."""

from fastapi import APIRouter

from hive.agents.factory import AgentRegistration, list_agents
from hive.api.routes import API_PREFIX

router = APIRouter(prefix=f"{API_PREFIX}/agents", tags=["agents"])


@router.get(
    "", description="List the agent kinds with their descriptions and param schemas."
)
async def list_agent_kinds() -> list[AgentRegistration]:
    """List the agent kinds with their descriptions and param schemas.

    Returns:
        One entry per registered kind, in registration order.
    """
    return list_agents()
