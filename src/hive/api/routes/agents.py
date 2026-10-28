"""Routes that describe the registered agent kinds and the shipped presets."""

from fastapi import APIRouter

from hive.agents.factory import AgentPreset, AgentRegistration, list_agents
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


@router.get(
    "/presets",
    description="List the shipped agent presets, such as `nm2` and `nm3`, with their "
    "spec and a short description, to offer as named strengths.",
)
async def list_agent_presets() -> list[AgentPreset]:
    """List the shipped agent presets with their spec and a short description.

    Returns:
        One entry per preset, sorted by name.
    """
    return AgentPreset.load_all()
