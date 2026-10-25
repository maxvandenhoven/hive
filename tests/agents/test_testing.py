import pytest

from hive.agents.testing import FakeClock, LocalTurnContext, TurnSubmission
from hive.engine.state import Move, PieceType

MOVE = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))


class TestFakeClock:
    def test_advances_by_step_after_each_read(self) -> None:
        clock = FakeClock(now=1.0, step=0.5)

        assert [clock(), clock(), clock()] == [1.0, 1.5, 2.0]

    def test_advances_manually(self) -> None:
        clock = FakeClock()
        clock.advance(2.0)

        assert clock() == 2.0


class TestLocalTurnContext:
    def test_stops_at_deadline(self) -> None:
        clock = FakeClock()
        turn = LocalTurnContext(budget_s=1.0, clock=clock)

        assert turn.remaining_seconds() == 1.0
        assert not turn.should_stop()
        clock.advance(1.0)
        assert turn.should_stop()
        assert turn.remaining_seconds() == 0.0

    def test_stops_when_stopped(self) -> None:
        turn = LocalTurnContext()
        turn.stop()

        assert turn.should_stop()

    def test_final_submission_closes_turn(self) -> None:
        turn = LocalTurnContext()
        turn.submit(None)
        assert not turn.closed
        assert not turn.should_stop()

        turn.submit(move=MOVE, final=True)
        assert turn.closed
        assert turn.should_stop()
        assert turn.move == MOVE

    def test_marks_submissions_after_stop(self) -> None:
        turn = LocalTurnContext()
        turn.submit(None)
        turn.stop()
        turn.submit(MOVE)
        assert turn.should_stop()
        turn.submit(MOVE)

        assert turn.submissions == [
            TurnSubmission(move=None, final=False, after_stop=False),
            TurnSubmission(move=MOVE, final=False, after_stop=False),
            TurnSubmission(move=MOVE, final=False, after_stop=True),
        ]

    def test_records_infos(self) -> None:
        turn = LocalTurnContext()
        turn.info(depth=1, nodes=20)
        turn.info(depth=2, pv=[None])

        assert turn.infos == [{"depth": 1, "nodes": 20}, {"depth": 2, "pv": [None]}]

    def test_move_requires_submission(self) -> None:
        with pytest.raises(LookupError, match="No move was submitted"):
            _ = LocalTurnContext().move
