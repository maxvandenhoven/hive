"""Routes that describe the registered agent kinds."""

from fastapi import APIRouter

from hive.agents.factory import list_agents
from hive.api.routes import API_PREFIX
from hive.api.schemas import AgentKindRead

router = APIRouter(prefix=f"{API_PREFIX}/agents", tags=["agents"])


@router.get(
    "", description="List the agent kinds with their descriptions and param schemas."
)
async def list_agent_kinds() -> list[AgentKindRead]:
    """List the agent kinds with their descriptions and param schemas.

    Returns:
        One entry per registered kind, in registration order.
    """
    return [
        AgentKindRead.from_registration(registration) for registration in list_agents()
    ]
