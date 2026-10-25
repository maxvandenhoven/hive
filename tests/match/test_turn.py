import multiprocessing
from collections.abc import Iterator
from multiprocessing.connection import Connection

import pytest

from hive.agents.testing import FakeClock
from hive.engine.state import Move, PieceType
from hive.match.records import TurnCloseReason
from hive.match.turn import (
    CandidateSelection,
    FailedMessage,
    IdleMessage,
    InfoMessage,
    PipeTurnContext,
    SubmissionMessage,
    WorkerMessage,
)

LEGAL_MOVES = [
    Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0)),
    Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0)),
]
ILLEGAL_MOVE = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(5, 5))


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


def collect_turn(
    events: list[tuple[float, WorkerMessage]], deadline: float = 1.0
) -> tuple[CandidateSelection, FakeClock]:
    """Run the selection policy of turn 1 over scripted messages."""
    clock = FakeClock()
    selection = CandidateSelection.collect(
        turn_id=1,
        legal_moves=LEGAL_MOVES,
        deadline=deadline,
        messages=ScriptedMessages(clock=clock, events=events),
        clock=clock,
    )
    return selection, clock


class TestCandidateSelection:
    def test_latest_legal_candidate_wins_at_deadline(self) -> None:
        selection, clock = collect_turn(
            [
                (0.1, SubmissionMessage(turn_id=1, move=LEGAL_MOVES[0], final=False)),
                (0.2, SubmissionMessage(turn_id=1, move=LEGAL_MOVES[1], final=False)),
            ]
        )

        assert selection.move == LEGAL_MOVES[1]
        assert selection.candidates == 2
        assert selection.close_reason is TurnCloseReason.DEADLINE
        assert not selection.returned
        assert clock.now == 1.0

    def test_final_closes_turn(self) -> None:
        selection, clock = collect_turn(
            [
                (0.1, SubmissionMessage(turn_id=1, move=LEGAL_MOVES[0], final=True)),
                (0.2, SubmissionMessage(turn_id=1, move=LEGAL_MOVES[1], final=False)),
            ]
        )

        assert selection.move == LEGAL_MOVES[0]
        assert selection.close_reason is TurnCloseReason.FINAL
        assert clock.now == 0.1

    def test_illegal_submissions_are_ignored_and_counted(self) -> None:
        selection, _ = collect_turn(
            [
                (0.1, SubmissionMessage(turn_id=1, move=LEGAL_MOVES[0], final=False)),
                (0.2, SubmissionMessage(turn_id=1, move=ILLEGAL_MOVE, final=False)),
                (0.3, SubmissionMessage(turn_id=1, move=ILLEGAL_MOVE, final=True)),
                (0.4, SubmissionMessage(turn_id=1, move=None, final=False)),
            ]
        )

        assert selection.move == LEGAL_MOVES[0]
        assert selection.illegal_submissions == 3
        assert selection.close_reason is TurnCloseReason.DEADLINE

    def test_returning_with_candidate_is_final(self) -> None:
        selection, clock = collect_turn(
            [
                (0.1, SubmissionMessage(turn_id=1, move=LEGAL_MOVES[0], final=False)),
                (0.2, IdleMessage(1)),
            ]
        )

        assert selection.returned
        assert selection.close_reason is TurnCloseReason.FINAL
        assert clock.now == 0.2

    @pytest.mark.parametrize(
        "events",
        [
            [],
            [(0.1, IdleMessage(1))],
            [(0.1, SubmissionMessage(turn_id=1, move=ILLEGAL_MOVE, final=False))],
        ],
        ids=["silent", "returned", "illegal"],
    )
    def test_no_candidate(self, events: list[tuple[float, WorkerMessage]]) -> None:
        selection, _ = collect_turn(events)

        assert not selection.has_candidate
        assert selection.close_reason is TurnCloseReason.NO_CANDIDATE

    def test_failure_keeps_candidate(self) -> None:
        selection, _ = collect_turn(
            [
                (0.1, SubmissionMessage(turn_id=1, move=LEGAL_MOVES[1], final=False)),
                (0.2, FailedMessage(turn_id=1, error="boom")),
            ]
        )

        assert selection.move == LEGAL_MOVES[1]
        assert selection.failure == "boom"
        assert selection.close_reason is TurnCloseReason.WORKER_FAILED

    def test_messages_of_other_turns_are_dropped(self) -> None:
        selection, _ = collect_turn(
            [
                (0.1, SubmissionMessage(turn_id=0, move=LEGAL_MOVES[0], final=True)),
                (0.2, IdleMessage(2)),
            ]
        )

        assert not selection.has_candidate
        assert not selection.returned

    def test_pass_is_a_candidate_when_legal(self) -> None:
        clock = FakeClock()
        messages = ScriptedMessages(
            clock=clock,
            events=[(0.1, SubmissionMessage(turn_id=1, move=None, final=True))],
        )

        selection = CandidateSelection.collect(
            turn_id=1, legal_moves=[None], deadline=1.0, messages=messages, clock=clock
        )

        assert selection.has_candidate
        assert selection.move is None
        assert selection.close_reason is TurnCloseReason.FINAL

    def test_streams_legal_submissions_and_infos(self) -> None:
        clock = FakeClock()
        events: list[tuple[float, WorkerMessage]] = [
            (0.1, SubmissionMessage(turn_id=1, move=ILLEGAL_MOVE, final=False)),
            (0.2, InfoMessage(turn_id=1, fields={"depth": 1})),
            (0.3, SubmissionMessage(turn_id=1, move=LEGAL_MOVES[0], final=False)),
        ]
        streamed: list[WorkerMessage] = []

        selection = CandidateSelection.collect(
            turn_id=1,
            legal_moves=LEGAL_MOVES,
            deadline=1.0,
            messages=ScriptedMessages(clock=clock, events=events),
            clock=clock,
            message_callback=streamed.append,
        )

        assert streamed == [events[1][1], events[2][1]]
        assert selection.last_info == {"depth": 1}

    def test_expired_deadline_receives_nothing(self) -> None:
        selection, _ = collect_turn(
            [(0.0, SubmissionMessage(turn_id=1, move=LEGAL_MOVES[0], final=True))],
            deadline=0.0,
        )

        assert not selection.has_candidate


@pytest.fixture(scope="function")
def pipe() -> Iterator[tuple[Connection, Connection]]:
    """Open a pipe, yielding the runner end and the worker end."""
    runner_conn, worker_conn = multiprocessing.Pipe()
    yield runner_conn, worker_conn
    runner_conn.close()
    worker_conn.close()


def drain(conn: Connection) -> list[object]:
    """Receive every message waiting on a connection."""
    messages = []

    while conn.poll():
        messages.append(conn.recv())

    return messages


class TestPipeTurnContext:
    def test_sends_submissions(self, pipe: tuple[Connection, Connection]) -> None:
        runner_conn, worker_conn = pipe
        turn = PipeTurnContext(
            conn=worker_conn, stop_event=multiprocessing.Event(), turn_id=3, deadline=1.0
        )

        turn.submit(LEGAL_MOVES[0])
        turn.submit(None, final=True)

        assert drain(runner_conn) == [
            SubmissionMessage(turn_id=3, move=LEGAL_MOVES[0], final=False),
            SubmissionMessage(turn_id=3, move=None, final=True),
        ]

    def test_stops_on_event_or_final(self, pipe: tuple[Connection, Connection]) -> None:
        _, worker_conn = pipe
        event = multiprocessing.Event()
        clock = FakeClock()
        stopped = PipeTurnContext(
            conn=worker_conn, stop_event=event, turn_id=1, deadline=1.0, clock=clock
        )
        closed = PipeTurnContext(
            conn=worker_conn, stop_event=multiprocessing.Event(), turn_id=1, deadline=1.0
        )

        assert not stopped.should_stop()
        clock.advance(2.0)
        assert stopped.remaining_seconds() == -1.0
        assert not stopped.should_stop()
        event.set()
        assert stopped.should_stop()

        closed.submit(LEGAL_MOVES[0], final=True)
        assert closed.should_stop()

    def test_rate_limits_info(self, pipe: tuple[Connection, Connection]) -> None:
        runner_conn, worker_conn = pipe
        clock = FakeClock()
        turn = PipeTurnContext(
            conn=worker_conn,
            stop_event=multiprocessing.Event(),
            turn_id=1,
            deadline=10.0,
            info_interval_s=1.0,
            clock=clock,
        )

        turn.info(depth=1)
        turn.info(depth=2)
        turn.info(depth=3)
        assert drain(runner_conn) == [InfoMessage(turn_id=1, fields={"depth": 1})]

        clock.advance(1.0)
        turn.info(depth=4)
        turn.info(depth=5)
        turn.flush()
        turn.flush()
        assert drain(runner_conn) == [
            InfoMessage(turn_id=1, fields={"depth": 4}),
            InfoMessage(turn_id=1, fields={"depth": 5}),
        ]

    def test_held_back_info_precedes_submission(
        self, pipe: tuple[Connection, Connection]
    ) -> None:
        runner_conn, worker_conn = pipe
        turn = PipeTurnContext(
            conn=worker_conn,
            stop_event=multiprocessing.Event(),
            turn_id=1,
            deadline=10.0,
            info_interval_s=1.0,
        )

        turn.info(depth=1)
        turn.info(depth=2)
        turn.submit(LEGAL_MOVES[0], final=True)

        assert drain(runner_conn) == [
            InfoMessage(turn_id=1, fields={"depth": 1}),
            InfoMessage(turn_id=1, fields={"depth": 2}),
            SubmissionMessage(turn_id=1, move=LEGAL_MOVES[0], final=True),
        ]
