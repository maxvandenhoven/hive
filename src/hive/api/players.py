"""The players of the sides of a game and where the game is played.

A side is a person, who may get hints from an agent, or a timed agent. The players and
the board location together tell the supported game setups apart (D26).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from hive.agents.factory import AgentSpec
from hive.engine.codec import JsonCodec

DEFAULT_AGENT_BUDGET_S = 5.0
"""The time budget of an agent decision in seconds when none is configured."""

type AgentBudget = Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
"""The time budget of an agent decision in seconds."""

PLAYER_NAME_MAX_LENGTH = 40
"""The longest name of a person playing a side."""

type PlayerName = Annotated[str, Field(min_length=1, max_length=PLAYER_NAME_MAX_LENGTH)]
"""The name of a person playing a side."""

type PlayerType = Literal["human", "agent"]
"""Whether a person or an agent plays a side."""


@dataclass(frozen=True, slots=True)
class HintAgent(JsonCodec):
    """An agent that suggests moves to the person playing a side, on request.

    Attributes:
        spec: The agent. Its params are checked when a game is created, not when a stored
            game is read.
        budget_s: The time budget of every hint in seconds.
    """

    spec: AgentSpec
    budget_s: AgentBudget = DEFAULT_AGENT_BUDGET_S


@dataclass(frozen=True, slots=True)
class HumanPlayer(JsonCodec):
    """A side played by a person, who enters every move of the side.

    Attributes:
        hint: The agent that suggests moves to the person, or `None` for no hints.
        name: The name of the person, such as a friend at the table, or `None` for the
            person using the app.
        type: Always `human`, which tells the player kinds apart in JSON.
    """

    hint: HintAgent | None = None
    name: PlayerName | None = None
    type: Literal["human"] = "human"


@dataclass(frozen=True, slots=True)
class AgentPlayer(JsonCodec):
    """A side played by an agent, whose moves are applied or made on the board.

    Attributes:
        spec: The agent. Its params are checked when a game is created, not when a stored
            game is read.
        budget_s: The time budget of every decision in seconds.
        type: Always `agent`, which tells the player kinds apart in JSON.
    """

    spec: AgentSpec
    budget_s: AgentBudget = DEFAULT_AGENT_BUDGET_S
    type: Literal["agent"] = "agent"


type PlayerConfig = Annotated[HumanPlayer | AgentPlayer, Field(discriminator="type")]
"""A human or an agent side, told apart by its `type`."""


class BoardLocation(StrEnum):
    """Where a game is played.

    On the `screen` the app is the board, so agent moves apply at once. At the `table` a
    physical board is played on, so a person makes every agent move on it and confirms it.
    """

    SCREEN = "screen"
    TABLE = "table"

    @classmethod
    def default_for(cls, white: PlayerConfig, black: PlayerConfig) -> "BoardLocation":
        """Get the board location of a game whose request names none.

        Args:
            white: The white side.
            black: The black side.

        Returns:
            `screen` for agent vs agent, otherwise `table`.
        """
        if isinstance(white, AgentPlayer) and isinstance(black, AgentPlayer):
            return cls.SCREEN

        return cls.TABLE

    def setup_error(self, white: PlayerConfig, black: PlayerConfig) -> str | None:
        """Check that a game with these players may be played at this location.

        The supported setups are human vs agent on the screen or at the table, human vs
        human with a hint agent on at least one side at the table, and agent vs agent on
        the screen.

        Args:
            white: The white side.
            black: The black side.

        Returns:
            Why the setup is not supported, or `None` if it is.
        """
        humans = [player for player in (white, black) if isinstance(player, HumanPlayer)]

        if not humans:
            if self is BoardLocation.TABLE:
                return (
                    "Agent vs agent games are played on the `screen`, not at the `table`."
                )

            return None

        if len(humans) == len((white, black)):
            if all(human.hint is None for human in humans):
                return (
                    "Human vs human games need a `hint` agent on at least one side; "
                    "human vs human without hints is not supported."
                )

            if self is BoardLocation.SCREEN:
                return (
                    "Human vs human games are played at the `table`, not on the `screen`."
                )

        return None
