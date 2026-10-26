"""The players of the sides of a game: a person at the table, or a timed agent."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from hive.agents.factory import AgentSpec
from hive.engine.codec import JsonCodec

DEFAULT_AGENT_BUDGET_S = 5.0
"""The time budget of an agent decision in seconds when none is configured."""


@dataclass(frozen=True, slots=True)
class HumanPlayer(JsonCodec):
    """A side played by a person at the table.

    Attributes:
        type: Always `human`, which tells the player kinds apart in JSON.
    """

    type: Literal["human"] = "human"


@dataclass(frozen=True, slots=True)
class AgentPlayer(JsonCodec):
    """A side played by an agent, whose moves a person executes on the board.

    Attributes:
        spec: The agent. Its params are checked when a game is created, not when a stored
            game is read.
        budget_s: The time budget of every decision in seconds.
        type: Always `agent`, which tells the player kinds apart in JSON.
    """

    spec: AgentSpec
    budget_s: Annotated[float, Field(gt=0.0, allow_inf_nan=False)] = (
        DEFAULT_AGENT_BUDGET_S
    )
    type: Literal["agent"] = "agent"


type PlayerConfig = Annotated[HumanPlayer | AgentPlayer, Field(discriminator="type")]
"""A human or an agent side, told apart by its `type`."""
