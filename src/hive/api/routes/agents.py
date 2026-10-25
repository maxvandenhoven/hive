"""Routes that describe the registered agent kinds."""

from fastapi import APIRouter

from hive.agents.factory import list_agents
from hive.api.schemas import AgentKindRead

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
def read_agent_kinds() -> list[AgentKindRead]:
    """List the agent kinds with their descriptions and param schemas."""
    return [
        AgentKindRead.from_registration(registration) for registration in list_agents()
    ]
