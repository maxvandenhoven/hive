import multiprocessing
from collections.abc import Iterator
from multiprocessing.connection import Connection

import pytest

from hive.agents.testing import FakeClock
from hive.engine.state import Move, PieceType
from hive.match.records import CloseReason
from hive.match.turn import (
    CandidateSelection,
    Failed,
    Idle,
    Info,
    PipeTurnContext,
    Submission,
    WorkerMessage,
)

_LEGAL = [Move(PieceType.QUEEN, None, (0, 0)), Move(PieceType.ANT, None, (0, 0))]
_ILLEGAL = Move(PieceType.QUEEN, None, (5, 5))


class ScriptedMessages:
    """A message source that delivers messages at fixed times on a fake clock."""

    def __init__(
        self, clock: FakeClock, events: list[tuple[float, WorkerMessage]]
    ) -> None:
        self.clock = clock
        self.events = list(events)

    def __call__(self, timeout: float) -> WorkerMessage | None:
        """Wait for the next message, advancing the clock to it or by the timeout."""
        if self.events and self.events[0][0] <= self.clock.now + timeout:
            at, message = self.events.pop(0)
            self.clock.now = max(self.clock.now, at)
            return message
        self.clock.advance(timeout)
        return None


def _collect(
    events: list[tuple[float, WorkerMessage]], deadline: float = 1.0
) -> tuple[CandidateSelection, FakeClock]:
    """Run the selection policy of turn 1 over scripted messages."""
    clock = FakeClock()
    selection = CandidateSelection.collect(
        1, _LEGAL, deadline, ScriptedMessages(clock, events), clock=clock
    )
    return selection, clock


class TestCandidateSelection:
    def test_latest_legal_candidate_wins_at_deadline(self) -> None:
        selection, clock = _collect(
            [
                (0.1, Submission(1, _LEGAL[0], False)),
                (0.2, Submission(1, _LEGAL[1], False)),
            ]
        )

        assert selection.move == _LEGAL[1]
        assert selection.candidates == 2
        assert selection.close_reason is CloseReason.DEADLINE
        assert not selection.returned
        assert clock.now == 1.0

    def test_final_closes_turn(self) -> None:
        selection, clock = _collect(
            [
                (0.1, Submission(1, _LEGAL[0], True)),
                (0.2, Submission(1, _LEGAL[1], False)),
            ]
        )

        assert selection.move == _LEGAL[0]
        assert selection.close_reason is CloseReason.FINAL
        assert clock.now == 0.1

    def test_illegal_submissions_are_ignored_and_counted(self) -> None:
        selection, _ = _collect(
            [
                (0.1, Submission(1, _LEGAL[0], False)),
                (0.2, Submission(1, _ILLEGAL, False)),
                (0.3, Submission(1, _ILLEGAL, True)),
                (0.4, Submission(1, None, False)),
            ]
        )

        assert selection.move == _LEGAL[0]
        assert selection.illegal_submissions == 3
        assert selection.close_reason is CloseReason.DEADLINE

    def test_returning_with_candidate_is_final(self) -> None:
        selection, clock = _collect(
            [(0.1, Submission(1, _LEGAL[0], False)), (0.2, Idle(1))]
        )

        assert selection.returned
        assert selection.close_reason is CloseReason.FINAL
        assert clock.now == 0.2

    @pytest.mark.parametrize(
        "events",
        [[], [(0.1, Idle(1))], [(0.1, Submission(1, _ILLEGAL, False))]],
        ids=["silent", "returned", "illegal"],
    )
    def test_no_candidate(self, events: list[tuple[float, WorkerMessage]]) -> None:
        selection, _ = _collect(events)

        assert not selection.has_candidate
        assert selection.close_reason is CloseReason.NO_CANDIDATE

    def test_failure_keeps_candidate(self) -> None:
        selection, _ = _collect(
            [(0.1, Submission(1, _LEGAL[1], False)), (0.2, Failed(1, "boom"))]
        )

        assert selection.move == _LEGAL[1]
        assert selection.failure == "boom"
        assert selection.close_reason is CloseReason.WORKER_FAILED

    def test_messages_of_other_turns_are_dropped(self) -> None:
        selection, _ = _collect([(0.1, Submission(0, _LEGAL[0], True)), (0.2, Idle(2))])

        assert not selection.has_candidate
        assert not selection.returned

    def test_pass_is_a_candidate_when_legal(self) -> None:
        clock = FakeClock()
        messages = ScriptedMessages(clock, [(0.1, Submission(1, None, True))])

        selection = CandidateSelection.collect(1, [None], 1.0, messages, clock=clock)

        assert selection.has_candidate
        assert selection.move is None
        assert selection.close_reason is CloseReason.FINAL

    def test_streams_legal_submissions_and_infos(self) -> None:
        clock = FakeClock()
        events: list[tuple[float, WorkerMessage]] = [
            (0.1, Submission(1, _ILLEGAL, False)),
            (0.2, Info(1, {"depth": 1})),
            (0.3, Submission(1, _LEGAL[0], False)),
        ]
        streamed: list[WorkerMessage] = []

        selection = CandidateSelection.collect(
            1,
            _LEGAL,
            1.0,
            ScriptedMessages(clock, events),
            clock=clock,
            on_message=streamed.append,
        )

        assert streamed == [events[1][1], events[2][1]]
        assert selection.last_info == {"depth": 1}

    def test_expired_deadline_receives_nothing(self) -> None:
        selection, _ = _collect([(0.0, Submission(1, _LEGAL[0], True))], deadline=0.0)

        assert not selection.has_candidate


@pytest.fixture(scope="function")
def pipe() -> Iterator[tuple[Connection, Connection]]:
    """Open a pipe, yielding the runner end and the worker end."""
    runner_conn, worker_conn = multiprocessing.Pipe()
    yield runner_conn, worker_conn
    runner_conn.close()
    worker_conn.close()


def _drain(conn: Connection) -> list[object]:
    """Receive every message waiting on a connection."""
    messages = []
    while conn.poll():
        messages.append(conn.recv())
    return messages


class TestPipeTurnContext:
    def test_sends_submissions(self, pipe: tuple[Connection, Connection]) -> None:
        runner_conn, worker_conn = pipe
        turn = PipeTurnContext(worker_conn, multiprocessing.Event(), 3, deadline=1.0)

        turn.submit(_LEGAL[0])
        turn.submit(None, final=True)

        assert _drain(runner_conn) == [
            Submission(3, _LEGAL[0], False),
            Submission(3, None, True),
        ]

    def test_stops_on_event_or_final(self, pipe: tuple[Connection, Connection]) -> None:
        _, worker_conn = pipe
        event = multiprocessing.Event()
        clock = FakeClock()
        stopped = PipeTurnContext(worker_conn, event, 1, deadline=1.0, clock=clock)
        closed = PipeTurnContext(worker_conn, multiprocessing.Event(), 1, deadline=1.0)

        assert not stopped.should_stop()
        clock.advance(2.0)
        assert stopped.remaining_seconds() == -1.0
        assert not stopped.should_stop()
        event.set()
        assert stopped.should_stop()

        closed.submit(_LEGAL[0], final=True)
        assert closed.should_stop()

    def test_rate_limits_info(self, pipe: tuple[Connection, Connection]) -> None:
        runner_conn, worker_conn = pipe
        clock = FakeClock()
        turn = PipeTurnContext(
            worker_conn,
            multiprocessing.Event(),
            1,
            deadline=10.0,
            info_interval_s=1.0,
            clock=clock,
        )

        turn.info(depth=1)
        turn.info(depth=2)
        turn.info(depth=3)
        assert _drain(runner_conn) == [Info(1, {"depth": 1})]

        clock.advance(1.0)
        turn.info(depth=4)
        turn.info(depth=5)
        turn.flush()
        turn.flush()
        assert _drain(runner_conn) == [Info(1, {"depth": 4}), Info(1, {"depth": 5})]

    def test_held_back_info_precedes_submission(
        self, pipe: tuple[Connection, Connection]
    ) -> None:
        runner_conn, worker_conn = pipe
        turn = PipeTurnContext(
            worker_conn, multiprocessing.Event(), 1, deadline=10.0, info_interval_s=1.0
        )

        turn.info(depth=1)
        turn.info(depth=2)
        turn.submit(_LEGAL[0], final=True)

        assert _drain(runner_conn) == [
            Info(1, {"depth": 1}),
            Info(1, {"depth": 2}),
            Submission(1, _LEGAL[0], True),
        ]
