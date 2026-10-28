import pytest

from hive.agents.factory import AgentSpec
from hive.api.players import (
    AgentPlayer,
    BoardLocation,
    HintAgent,
    HumanPlayer,
    PlayerConfig,
)

AGENT = AgentPlayer(spec=AgentSpec("random"))
HUMAN = HumanPlayer()
HINTED = HumanPlayer(hint=HintAgent(spec=AgentSpec("random"), budget_s=1.0))

SETUP_MATRIX: list[tuple[PlayerConfig, PlayerConfig, BoardLocation, str | None]] = [
    (HUMAN, AGENT, BoardLocation.SCREEN, None),
    (HUMAN, AGENT, BoardLocation.TABLE, None),
    (AGENT, HINTED, BoardLocation.SCREEN, None),
    (AGENT, HINTED, BoardLocation.TABLE, None),
    (HINTED, HUMAN, BoardLocation.TABLE, None),
    (HUMAN, HINTED, BoardLocation.TABLE, None),
    (HINTED, HINTED, BoardLocation.TABLE, None),
    (HINTED, HUMAN, BoardLocation.SCREEN, "played at the `table`"),
    (HUMAN, HUMAN, BoardLocation.TABLE, "need a `hint` agent"),
    (HUMAN, HUMAN, BoardLocation.SCREEN, "need a `hint` agent"),
    (AGENT, AGENT, BoardLocation.SCREEN, None),
    (AGENT, AGENT, BoardLocation.TABLE, "played on the `screen`"),
]
"""White, black, the board location and part of the error, or `None` if supported."""


class TestBoardLocation:
    @pytest.mark.parametrize(("white", "black", "location", "error"), SETUP_MATRIX)
    def test_setup_matrix(
        self,
        white: PlayerConfig,
        black: PlayerConfig,
        location: BoardLocation,
        error: str | None,
    ) -> None:
        message = location.setup_error(white=white, black=black)

        if error is None:
            assert message is None
        else:
            assert message is not None
            assert error in message

    @pytest.mark.parametrize(
        ("white", "black", "location"),
        [
            (AGENT, AGENT, BoardLocation.SCREEN),
            (HUMAN, AGENT, BoardLocation.TABLE),
            (AGENT, HUMAN, BoardLocation.TABLE),
            (HINTED, HUMAN, BoardLocation.TABLE),
        ],
    )
    def test_default_for_players(
        self, white: PlayerConfig, black: PlayerConfig, location: BoardLocation
    ) -> None:
        assert BoardLocation.default_for(white=white, black=black) is location


class TestHumanPlayer:
    def test_reads_without_hint(self) -> None:
        assert HumanPlayer.from_json({"type": "human"}) == HUMAN

    def test_round_trips_hint(self) -> None:
        assert HumanPlayer.from_json(HINTED.to_json()) == HINTED
